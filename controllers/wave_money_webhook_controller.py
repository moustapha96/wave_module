

from odoo import http, fields
from odoo.http import request, Response
import logging
import json
from datetime import datetime

_logger = logging.getLogger(__name__)

class WaveMoneyWebhookController(http.Controller):

    def _map_wave_status_to_odoo(self, checkout_status, payment_status):
        status_map = {
            ('complete', 'succeeded'): 'completed',
            ('failed', 'any'): 'failed',
            ('any', 'failed'): 'failed',
            ('cancelled', 'any'): 'cancelled',
            ('any', 'cancelled'): 'cancelled',
            ('expired', 'any'): 'expired',
        }
        return status_map.get((checkout_status, payment_status), 'pending')

    @http.route('/wave/webhook', type='http', auth='public', csrf=False, methods=['POST'])
    def wave_webhook(self, **kwargs):
        try:
            config = request.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
            if not config:
                return self._json_response({'error': 'Configuration not found'}, 400)

            body = request.httprequest.get_data()
            try:
                webhook_data = json.loads(body.decode('utf-8'))
            except json.JSONDecodeError:
                return self._json_response({'error': 'Invalid JSON'}, 400)

            result = self._process_wave_webhook(webhook_data)
            return self._json_response(result, 200)

        except Exception as e:
            _logger.exception("Webhook error: %s", str(e))
            return self._json_response({'error': 'Internal server error'}, 500)

    def _process_wave_webhook(self, webhook_data):
        event_type = webhook_data.get('type') or webhook_data.get('event')
        _logger.info(f"Processing Wave event: {event_type}")

        if event_type != "checkout.session.completed":
            return {'success': False, 'error': 'Unhandled event'}

        session = webhook_data.get('data', {})
        session_id = session.get('id')
        if not session_id:
            return {'success': False, 'error': 'Missing session ID'}

        transaction = request.env['wave.transaction'].sudo().search([('wave_id', '=', session_id)], limit=1)
        if not transaction:
            return {'success': False, 'error': 'Transaction not found'}

        checkout_status = session.get('checkout_status', '').lower()
        payment_status = session.get('payment_status', '').lower()
        new_status = self._map_wave_status_to_odoo(checkout_status, payment_status)

        transaction.write({
            'status': new_status,
            'updated_at': fields.Datetime.now(),
            'completed_at': self.convert_iso_format_to_custom_format(session.get('when_completed')),
            'webhook_data': json.dumps(webhook_data),
            'checkout_status': checkout_status,
            'payment_status': payment_status,
        })

        if new_status == 'completed':
            # pourcentage = (100 * transaction.amount) / transaction.order_id.amount_total if transaction.order_id.amount_total else 0
            # creer un paiment 
            resultat = self._create_payment_transaction(transaction)
            if resultat:
                _logger.info(f"Payment completed for transaction {transaction.reference} (custom_id: {transaction.transaction_id})")
            else:
                _logger.error(f"Payment creation failed for transaction {transaction.reference} (custom_id: {transaction.transaction_id})")
            # invoice = self.create_advance_invoice(transaction.order_id, pourcentage)
            # if invoice:
            #     return self.process_payment(transaction.order_id, invoice, transaction.amount, request.env.company)
            # else:
            #     return {'success': False, 'error': 'Invoice creation failed'}

        return {'success': True}

    def convert_iso_format_to_custom_format(self, iso_date):
        try:
            return datetime.strptime(iso_date, "%Y-%m-%dT%H:%M:%SZ").strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def _json_response(self, data, status):
        return Response(json.dumps(data), status=status, mimetype='application/json')

    def create_advance_invoice(self, order, percentage):
        """
        Crée une facture d'acompte en utilisant l'assistant Odoo
        Args:
            order: Objet sale.order
            percentage: Pourcentage de l'acompte
        Returns:
            account.move: Facture d'acompte créée
        """
        user = request.env['res.users'].sudo().browse(request.env.uid)
        if not user or user._is_public():
            admin_user = request.env.ref('base.user_admin')
            request.env = request.env(user=admin_user.id)
            _logger.info("Création de la facture d'acompte pour la commande %s avec pourcentage %.2f%% avec l'utilisateur administrateur par défaut", order.name, percentage)

        try:
            if order.state not in ['sale', 'done']:
                order.action_confirm()

            context = {
                'active_ids': [order.id],
                'active_model': 'sale.order',
                'active_id': order.id,
                'default_advance_payment_method': 'percentage',
            }

            advance_payment_wizard = request.env['sale.advance.payment.inv'].sudo().with_context(context).create({
                'advance_payment_method': 'percentage',
                'amount': percentage,
            })

            if not advance_payment_wizard.sale_order_ids:
                advance_payment_wizard.sale_order_ids = [(6, 0, [order.id])]

            if not advance_payment_wizard.sale_order_ids:
                _logger.error("Impossible d'assigner la commande %s à l'assistant d'acompte", order.name)
                return None

            result = advance_payment_wizard.create_invoices()

            if isinstance(result, dict) and 'res_id' in result:
                invoice_id = result['res_id']
                invoice = request.env['account.move'].sudo().browse(invoice_id)
            else:
                invoice = order.invoice_ids.filtered(
                    lambda inv: inv.state == 'draft'
                ).sorted('create_date', reverse=True)[:1]

            if invoice:
                if invoice.state == 'draft':
                    invoice.action_post()
                _logger.info("Facture d'acompte créée: %s pour commande %s (%.2f%%)",
                            invoice.name, order.name, percentage)
                return invoice
            else:
                _logger.error("Impossible de créer la facture d'acompte pour la commande %s", order.name)
                return None

        except Exception as e:
            _logger.exception("Erreur lors de la création de la facture d'acompte: %s", str(e))
            return None

    def process_payment(self, order, invoice, amount, company):
        """
        Traite le paiement pour la facture d'acompte
        Args:
            order: Commande de vente
            invoice: Facture d'acompte
            amount: Montant du paiement
            company: Société
        Returns:
            dict: Résultat du traitement
        """
        user = request.env['res.users'].sudo().browse(request.env.uid)
        if not user or user._is_public():
            admin_user = request.env.ref('base.user_admin')
            request.env = request.env(user=admin_user.id)
            _logger.info("Traitement du paiement pour la facture d'acompte %s avec l'utilisateur administrateur par défaut", invoice.name)

        try:
            journal = request.env['account.journal'].sudo().search([
                ('code', '=', 'CSH1'),
                ('company_id', '=', company.id)
            ], limit=1)

            if not journal:
                journal = request.env['account.journal'].sudo().search([
                    ('type', 'in', ['cash', 'bank']),
                    ('company_id', '=', company.id)
                ], limit=1)

            payment_method_line = request.env['account.payment.method.line'].sudo().search([
                ('journal_id', '=', journal.id),
                ('payment_method_id.payment_type', '=', 'inbound')
            ], limit=1)

            payment = self._register_payment(order, invoice, amount, journal.id, payment_method_line.id)
            if not payment:
                return {'success': False, 'error': 'Erreur lors de l\'enregistrement du paiement'}

            self._reconcile_payment_with_invoice(payment, invoice)

            return {
                'success': True,
                'payment_id': payment.id,
                'invoice_id': invoice.id,
                'amount': amount,
                'message': 'Paiement d\'acompte enregistré avec succès'
            }

        except Exception as e:
            _logger.exception("Erreur lors du traitement du paiement: %s", str(e))
            return {'success': False, 'error': str(e)}

    def _register_payment(self, order, invoice, amount, journal_id, payment_method_line_id=None):
        """
        Enregistre un paiement sur la facture.

        Args:
            order: Commande de vente
            invoice: objet account.move
            amount: montant du paiement
            journal_id: ID du journal (ex: banque)

        Returns:
            account.payment
        """
        try:
            payment_obj = request.env['account.payment'].create({
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': invoice.partner_id.id,
                'amount': amount,
                'journal_id': journal_id,
                'payment_method_line_id': payment_method_line_id or request.env['account.payment.method.line'].search([('name', '=', 'Manual'), ('payment_method_id.payment_type', '=', 'inbound')], limit=1).id,
                'date': fields.Date.today(),
                'ref': f"{invoice.name}",
                'sale_id': order.id,
                'is_reconciled': True,
            })
            payment_obj.action_post()
            return payment_obj
        except Exception as e:
            _logger.exception("Erreur lors de l'enregistrement du paiement : %s", str(e))
            return None

    def _reconcile_payment_with_invoice(self, payment, invoice):
        """
        Réconcilie le paiement avec la facture

        Args:
            payment: Objet account.payment
            invoice: Objet account.move
        """
        try:
            invoice_lines = invoice.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable' and not line.reconciled
            )

            if not invoice_lines:
                invoice_lines = invoice.line_ids.filtered(
                    lambda line: line.account_id.internal_type == 'receivable' and not line.reconciled
                )

            payment_lines = payment.move_id.line_ids.filtered(
                lambda line: line.account_id.account_type == 'asset_receivable'
            )

            if not payment_lines:
                payment_lines = payment.move_id.line_ids.filtered(
                    lambda line: line.account_id.internal_type == 'receivable'
                )

            lines_to_reconcile = invoice_lines + payment_lines
            if lines_to_reconcile:
                lines_to_reconcile.reconcile()
                _logger.info("Paiement %s réconcilié avec facture d'acompte %s", payment.name, invoice.name)
            else:
                _logger.warning("Aucune ligne à réconcilier trouvée pour le paiement %s et la facture %s",
                        payment.name, invoice.name)

        except Exception as e:
            _logger.exception("Erreur lors de la réconciliation du paiement: %s", str(e))
            return None

    def _create_payment_transaction(self, transaction):
        try:
            order = transaction.order_id
            company = order.company_id
            partner = order.partner_id
            amount = transaction.amount

            journal = request.env['account.journal'].sudo().search([('code', '=', 'CSH1'), ('company_id', '=', company.id)], limit=1)
            payment_method = request.env['account.payment.method'].sudo().search([('payment_type', '=', 'inbound')], limit=1)
            payment_method_line = request.env['account.payment.method.line'].sudo().search([('payment_method_id', '=', payment_method.id), ('journal_id', '=', journal.id)], limit=1)

            if not journal:
                journal = request.env['account.journal'].sudo().search([('type', 'in', ['cash', 'bank']), ('company_id', '=', company.id)], limit=1)

            if not payment_method:
                payment_method = request.env['account.payment.method'].sudo().search([('payment_type', '=', 'inbound')], limit=1)

            if not payment_method_line:
                payment_method_line = request.env['account.payment.method.line'].sudo().search([('payment_method_id', '=', payment_method.id), ('journal_id', '=', journal.id)], limit=1)

            if not company:
                company = request.env['res.company'].sudo().search([('id', '=', 1)], limit=1)

            if order and order.state != 'sale':
                order.action_confirm()

            if order.advance_payment_status != 'paid':
                account_payment = request.env['account.payment'].sudo().create({
                    'payment_type': 'inbound',
                    'partner_type': 'customer',
                    'partner_id': partner.id,
                    'amount': amount,
                    'journal_id': journal.id,
                    'currency_id': journal.currency_id.id,
                    'payment_method_line_id': payment_method_line.id,
                    'payment_method_id': payment_method.id,
                    'sale_id': order.id,
                    'ref': order.name
                })
                if account_payment:
                    account_payment.action_post()
                    return True
                else:
                    return False

        except Exception as e:
            _logger.error(f"Error handling completed payment: {str(e)}")
            return False