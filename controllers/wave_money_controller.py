
from odoo import http, fields
from odoo.http import request, Response
import requests
import hmac
import hashlib
import json
import logging
import werkzeug
from datetime import datetime
import base64


_logger = logging.getLogger(__name__)

class WaveMoneyController(http.Controller):
    
    @http.route('/api/payment/wave/initiate', type='http', auth='public', cors='*', methods=['POST'], csrf=False)
    def initiate_wave_payment(self, **kwargs):
        """Initier un paiement Wave avec checkout sessions"""
        try:
            # Validation des paramètres requis
            data = json.loads(request.httprequest.data)
            transaction_id = data.get('transaction_id')
            order_id = data.get('order_id')
            partner_id = data.get('partner_id')
            phone_number = data.get('phoneNumber')
            amount = data.get('amount')
            description = data.get('description', 'Payment via Wave')
            currency = data.get('currency', 'XOF')
            reference = data.get('reference')
            success_url = data.get('success_url')

            # Validation des champs obligatoires
            if not all([transaction_id, order_id, partner_id , phone_number , amount]):
                return self._make_response({'message': "Missing required fields: transaction_id, order_id, partner_id"}, 400)
                
            
            # Réccupérer la configuration Wave active
            config = request.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
            if not config:
                return {'error': 'Wave configuration not found', 'success': False}

            # Vérifier l'existence de l'order et du partner
            order = request.env['sale.order'].sudo().browse(int(order_id)) if order_id else None
            partner = request.env['res.partner'].sudo().browse(int(partner_id)) if partner_id else None
           
            if not order:
                return self._make_response({'message': "la commande n'exite pas"}, 400)
            if not partner:
                return self._make_response({'message': "le partner n'exite pas"}, 400)

            # Vérifier si payment.details existe déjà avec ce transaction_id
        
            # Vérifier si la transaction Wave existe déjà
            existing_tx = request.env['wave.transaction'].sudo().search([('transaction_id', '=', transaction_id)], limit=1)
            if existing_tx:
               
                return self._make_response({
                        'success': True,
                        'transaction_id': existing_tx.transaction_id,
                        'wave_id': existing_tx.wave_id,
                        'session_id': existing_tx.wave_id,
                        'payment_url': existing_tx.payment_link_url,
                        'status': existing_tx.status or 'pending',
                        'order_id': existing_tx.order_id.id,
                        'partner_id': existing_tx.partner_id.id,
                        'reference': existing_tx.reference,
                        'success_url': success_url,
                        'existe': True
                    }, 200)

            payload = {
                "amount": amount,
                "currency": currency,
                # "success_url":  f"https://dev.ccbmshop.com/wave-paiement?transaction={transaction_id}",
                "success_url":  f"https://www.ccbmshop.com/wave-paiement?transaction={transaction_id}",
                "error_url": config.callback_url
            }

            headers = {
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            }

            # Appel à l'API Wave checkout sessions
            response = requests.post(
                "https://api.wave.com/v1/checkout/sessions", 
                json=payload, 
                headers=headers,
                timeout=30
            )

            if response.status_code in [200, 201]:
                data = response.json()
                _logger.info(f"Wave checkout sessions response: {data}")
                # Créer la transaction dans Odoo
                wave_transaction = request.env['wave.transaction'].sudo().create({
                    'wave_id': data.get('id'),
                    'transaction_id': transaction_id,
                    'amount': amount,
                    'currency': currency,
                    'status': 'pending',
                    'phone': phone_number,
                    'reference': reference,
                    'description': description,
                    'payment_link_url': data.get('wave_launch_url') or data.get('checkout_url'),
                    'wave_response': json.dumps(data),
                    'order_id': order.id,
                    'partner_id': partner.id,
                    'checkout_status': data.get('checkout_status'),
                    'payment_status': data.get('payment_status'),
                })

                return self._make_response({
                    'success': True,
                    'transaction_id': wave_transaction.transaction_id,
                    'wave_id': data.get('id'),
                    'session_id': data.get('id'),
                    'payment_url': data.get('wave_launch_url') or data.get('checkout_url'),
                    'status': 'pending',
                    'order_id': wave_transaction.order_id.id,
                    'partner_id': wave_transaction.partner_id.id,
                    'reference': reference,
                    'checkout_status': data.get('checkout_status'),
                    'payment_status': data.get('payment_status'),
                }, 200)
                
            else:
                _logger.error(f"Wave API Error: {response.status_code} - {response.text}")
                return self._make_response(response.text, 400)
                

        except Exception as e:
            _logger.error(f"Error initiating Wave payment: {str(e)}")
            return self._make_response( str(e), 400)
    

    @http.route('/api/payment/wave/status/<string:transaction_id>', type='http', auth='public', cors='*', methods=['GET'])
    def get_wave_payment_status(self, transaction_id , **kwargs):
        """Vérifier le statut d'un paiement Wave"""
        try:
            if not transaction_id:
                return Response(json.dumps({'error': 'Paiement wave avec cette transaction_id nexiste pas'}), status=400, mimetype='application/json')

            # Rechercher la transaction selon les paramètres fournis
            transaction = None

            # Priorité 1: transaction_id (notre ID personnalisé)
            if transaction_id:
                transaction = request.env['wave.transaction'].sudo().search([('transaction_id', '=', transaction_id)], limit=1)
                result = self._refresh_transaction_status(transaction)
                if result:
                    transaction_up = request.env['wave.transaction'].sudo().search([('transaction_id', '=', transaction_id)], limit=1)


                    return self._make_response({
                        'success': True,
                        'transaction_id': transaction_up.transaction_id,
                        'custom_transaction_id': transaction_up.transaction_id,
                        'wave_id': transaction_up.wave_id,
                        'session_id': transaction_up.wave_id,
                        'reference': transaction_up.reference,
                        'status': transaction_up.status,
                        'checkout_status': transaction_up.checkout_status,
                        'payment_status': transaction_up.payment_status,
                        'amount': transaction_up.amount,
                        'currency': transaction_up.currency,
                        'phone': transaction_up.phone,
                        'description': transaction_up.description,
                        'payment_url': transaction_up.payment_link_url,
                        'order_id': transaction_up.order_id.id if transaction.order_id else False,
                        'order_type' : transaction_up.order_id.type_sale,
                        'order': self._order_to_dict(transaction_up.order_id),
                        'type_sale': transaction_up.order_id.type_sale,
                        'partner_id': transaction_up.partner_id.id if transaction.partner_id else False,
                        'created_at': transaction_up.created_at.isoformat() if transaction.created_at else None,
                        'updated_at': transaction_up.updated_at.isoformat() if transaction.updated_at else None,
                        'completed_at': transaction_up.completed_at.isoformat() if transaction.completed_at else None
                    }, 200)
                


                else:
                    return self._make_response({
                        'success': True,
                        'transaction_id': transaction.transaction_id,
                        'wave_id': transaction.wave_id,
                        'session_id': transaction.wave_id,
                        'payment_url': transaction.payment_link_url,
                        'status': transaction.status or 'pending',
                        'order_id': transaction.order_id.id,
                        'partner_id': transaction.partner_id.id,
                        'reference': transaction.reference,
                        'order': self._order_to_dict(transaction.order_id),
                        'existe': True
                    }, 200)

            return self._make_response({"error": "Transaction not found"}, 400)

        except Exception as e:
            _logger.error(f"Error getting Wave payment status: {str(e)}")
            return self._make_response({"error": str(e)}, 400)


    
    @http.route('/api/payment/wave/session/<string:session_id>', type='http', auth='public', cors='*', methods=['GET'])
    def get_wave_session(self, session_id, **kwargs):
        """Récupérer les détails d'une session Wave par son ID"""
        try:
            # Récupérer la configuration Wave active
            config = request.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
            if not config:
                return Response(json.dumps({'error': 'Configuration not found'}), status=200, mimetype='application/json')

            # Utiliser la méthode du modèle pour récupérer la session
            session_data = config.get_session_by_id(session_id)
            
            if session_data:
                # Rechercher la transaction correspondante
                transaction = request.env['wave.transaction'].sudo().search([('wave_id', '=', session_id)], limit=1)
                
                result = {
                    'success': True,
                    'session': session_data
                }

                transaction.write({
                    'wave_response': json.dumps(session_data),
                    'status': 'completed' if session_data.get('status') == 'succeeded' else 'pending',
                    'webhook_data': json.dumps(session_data),
                })

                if transaction:
                    result['transaction'] = {
                        'id': transaction.id,
                        'custom_transaction_id': transaction.transaction_id,
                        'status': transaction.status,
                        'reference': transaction.reference
                    }
                
                return Response(json.dumps(result), status=200, mimetype='application/json')
            else:
                return Response(json.dumps({'error': 'erreur'}), status=200, mimetype='application/json')

        except Exception as e:
            _logger.error(f"Error getting Wave session: {str(e)}")
            return Response(json.dumps({'error': f'Internal error: {str(e)}', 'success': False}), status=200, mimetype='application/json')

    @http.route('/api/payment/wave/refund', type='json', auth='public', cors='*', methods=['POST'])
    def refund_wave_payment(self, **kwargs):
        """Rembourser un paiement Wave"""
        try:
            session_id = kwargs.get('session_id')
            reference = kwargs.get('reference')
            custom_transaction_id = kwargs.get('custom_transaction_id')

            if not session_id and not reference and not custom_transaction_id:
                return {'error': 'session_id, reference or custom_transaction_id is required', 'success': False}

            # Récupérer la configuration Wave active
            config = request.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
            if not config:
                return {'error': 'Wave configuration not found', 'success': False}

            # Trouver la transaction
            transaction = None
            if custom_transaction_id:
                transaction = request.env['wave.transaction'].sudo().search([('transaction_id', '=', custom_transaction_id)], limit=1)
            elif reference:
                transaction = request.env['wave.transaction'].sudo().search([('reference', '=', reference)], limit=1)
            elif session_id:
                transaction = request.env['wave.transaction'].sudo().search([('wave_id', '=', session_id)], limit=1)

            if not transaction:
                return {'error': 'Transaction not found', 'success': False}

            session_id = transaction.wave_id

            # Utiliser la méthode du modèle pour rembourser
            refund_data = config.refund_transaction(session_id)
            
            if refund_data:
                # Mettre à jour la transaction
                transaction.write({
                    'status': 'refunded',
                    'updated_at': fields.Datetime.now(),
                    'wave_response': json.dumps(refund_data)
                })

                return {
                    'success': True,
                    'refund': refund_data,
                    'transaction_id': transaction.id,
                    'custom_transaction_id': transaction.transaction_id,
                    'message': 'Refund processed successfully'
                }
            else:
                return {'error': 'Refund failed', 'success': False}

        except Exception as e:
            _logger.error(f"Error refunding Wave payment: {str(e)}")
            return {'error': f'Internal error: {str(e)}', 'success': False}


    def _verify_wave_signature(self, body, signatures, timestamp, webhook_secret):
        if not timestamp or not signatures:
            return False

        payload = f"{timestamp}.{body.decode('utf-8')}"
        _logger.info(f"Wave webhook payload function: {payload}")

        # Calculer la valeur HMAC attendue
        computed_hmac = hmac.new(webhook_secret.encode('utf-8'), payload.encode('utf-8'), hashlib.sha256).hexdigest()
        _logger.info(f"Wave webhook signatures computed: {computed_hmac in signatures}")
        _logger.info(f"Wave webhook computed HMAC function: {computed_hmac}")
        _logger.info(f"Wave webhook signatures: {signatures}")

        return computed_hmac in signatures

    @http.route('/wave/payment/callback', type='http', auth='public', csrf=False, methods=['GET', 'POST'])
    def wave_payment_callback(self, **kwargs):
        """Gérer les callbacks de paiement Wave"""
        try:
            session_id = kwargs.get('session_id') or kwargs.get('id')
            status = kwargs.get('status')
            reference = kwargs.get('client_reference')
            _logger.info(f"Wave callback received: session_id={session_id}, status={status}, reference={reference}")
            if session_id:
                # Rechercher la transaction
                transaction = request.env['wave.transaction'].sudo().search([
                    '|',
                    ('wave_id', '=', session_id),
                    ('reference', '=', reference)
                ], limit=1)
                if transaction:
                    # Récupérer les détails de la session depuis Wave
                    config = request.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
                    if config:
                        session_data = config.get_session_by_id(session_id)
                        if session_data:
                            # Mettre à jour le statut selon les données de la session
                            checkout_status = session_data.get('checkout_status', '').lower()
                            payment_status = session_data.get('payment_status', '').lower()
                            odoo_status = self._map_wave_status_to_odoo(checkout_status, payment_status)

                            transaction.write({
                                'status': odoo_status,
                                'updated_at': fields.Datetime.now(),
                                'wave_response': json.dumps(session_data),
                                'checkout_status': checkout_status,
                                'payment_status': payment_status,
                            })
                            # Déclencher les actions selon le statut
                            if odoo_status == 'completed':
                                self._handle_payment_completed(transaction, session_data)
                            elif odoo_status == 'failed':
                                self._handle_payment_failed(transaction, session_data)
            # Rediriger vers une page de succès ou d'erreur
            if status == 'success' or status == 'completed':
                return request.redirect('/payment/success')
            else:
                return request.redirect('/payment/error')
        except Exception as e:
            _logger.error(f"Error processing Wave callback: {str(e)}")
            return request.redirect('/payment/error')

    def _map_wave_status_to_odoo(self, checkout_status, payment_status):
        """Mapper les statuts Wave vers les statuts Odoo"""
        checkout_status = checkout_status.lower()
        payment_status = payment_status.lower()

        if checkout_status == 'complete' and payment_status == 'succeeded':
            return 'completed'
        elif checkout_status == 'failed' or payment_status == 'failed':
            return 'failed'
        elif checkout_status == 'cancelled' or payment_status == 'cancelled':
            return 'cancelled'
        elif checkout_status == 'expired':
            return 'expired'
        else:
            return 'pending'

    def _handle_payment_completed(self, transaction, payment_data):
        """Gérer un paiement complété"""
        try:
            order = transaction.order_id
            
            resultat = self._create_payment_transaction(transaction)
            if resultat:
                _logger.info(f"Payment completed for transaction {transaction.reference} (custom_id: {transaction.transaction_id})")
            return resultat
                    
            
        except Exception as e:
            _logger.error(f"Error handling completed payment: {str(e)}")

    def _handle_payment_failed(self, transaction, payment_data):
        """Gérer un paiement échoué"""
        try:
            # Log d'échec
            _logger.warning(f"Payment failed for transaction {transaction.reference} (custom_id: {transaction.transaction_id})")
            
            # # Optionnel: Annuler la commande liée
            # if transaction.order_id:
            #     transaction.order_id.write({
            #         'state': 'cancel',
            #         # 'wave_payment_failed': True
            #     })

        except Exception as e:
            _logger.error(f"Error handling failed payment: {str(e)}")

    def _refresh_transaction_status(self, transaction):
        """Rafraîchir le statut d'une transaction depuis l'API Wave"""
        try:
            _logger.info(f"Refreshing status for transaction {transaction.id}")
            config = request.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
            if not config:
                return False
            # Utiliser la méthode du modèle pour récupérer la session
            session_data = config.get_session_by_id(transaction.wave_id)

            if session_data:
                wave_status = session_data.get('status', '').lower()
                checkout_status = session_data.get('checkout_status', '').lower()
                payment_status = session_data.get('payment_status', '').lower()
                
                new_status = self._map_wave_status_to_odoo(checkout_status, payment_status)

                if new_status != transaction.status:
                    _logger.info(f"Updating status of transaction {transaction.id} from {transaction.status} to {new_status}")
                    transaction.write({
                        'status': new_status,
                        'updated_at': fields.Datetime.now(),
                        'wave_response': json.dumps(session_data),
                        'checkout_status': session_data.get('checkout_status'),
                        'payment_status': session_data.get('payment_status'),
                        'completed_at' : session_data.get('when_completed'),
                    })
                return True
        except Exception as e:
            _logger.error(f"Error refreshing transaction status: {str(e)}")
            return False

    def _make_response(self, data, status):
        return request.make_response(
            json.dumps(data),
            status=status,
            headers={'Content-Type': 'application/json'}
        )

    # def _create_advance_invoice(self, transaction,order, percentage):
    #     """
    #     Crée une facture d'acompte en utilisant l'assistant Odoo
        
    #     Args:
    #         order: Objet sale.order
    #         percentage: Pourcentage de l'acompte
        
    #     Returns:
    #         account.move: Facture d'acompte créée
    #     """
    #     try:

    #         # S'assurer que la commande est confirmée
    #         if order.state not in ['sale', 'done']:
    #             order.action_confirm()

    #         # Définir le contexte avec les commandes sélectionnées AVANT de créer l'assistant
    #         context = {
    #             'active_ids': [order.id],
    #             'active_model': 'sale.order',
    #             'active_id': order.id,
    #             'default_advance_payment_method': 'percentage',
    #         }
            
    #         # Créer l'assistant de facture d'acompte avec le contexte approprié
    #         advance_payment_wizard = request.env['sale.advance.payment.inv'].sudo().with_context(context).create({
    #             'advance_payment_method': 'percentage',  # Méthode par pourcentage
    #             'amount': percentage,  # Pourcentage de l'acompte
    #         })
            
    #         # Vérifier que l'assistant a bien récupéré la commande
    #         if not advance_payment_wizard.sale_order_ids:
    #             # Forcer l'assignation de la commande si elle n'est pas automatiquement détectée
    #             advance_payment_wizard.sale_order_ids = [(6, 0, [order.id])]
            
    #         # Vérifier à nouveau
    #         if not advance_payment_wizard.sale_order_ids:
    #             _logger.error("Impossible d'assigner la commande %s à l'assistant d'acompte", order.name)
    #             return None
            
    #         # Créer la facture d'acompte
    #         result = advance_payment_wizard.create_invoices()
            
    #         # Récupérer la facture créée
    #         if isinstance(result, dict) and 'res_id' in result:
    #             invoice_id = result['res_id']
    #             invoice = request.env['account.move'].sudo().browse(invoice_id)
    #         else:
    #             # Chercher la dernière facture créée pour cette commande
    #             invoice = order.invoice_ids.filtered(
    #                 lambda inv: inv.state == 'draft'
    #             ).sorted('create_date', reverse=True)[:1]
            
    #         if invoice:
    #             # Valider la facture si elle n'est pas déjà validée
    #             if invoice.state == 'draft':
    #                 invoice.action_post()
    #             _logger.info("Facture d'acompte créée: %s pour commande %s (%.2f%%)", 
    #                        invoice.name, order.name, percentage)
    #             return invoice
    #         else:
    #             _logger.error("Impossible de créer la facture d'acompte pour la commande %s", order.name)
    #             return None

    #     except Exception as e:
    #         _logger.exception("Erreur lors de la création de la facture d'acompte: %s", str(e))
    #         # Fallback: créer une facture d'acompte manuellement
    #         return None
    
    def _order_to_dict(self, order):
        return {
            'id': order.id,
            'type_sale': order.type_sale,
            'name': order.name,
            'partner_id': order.partner_id.id,
            'type_sale': order.type_sale,
            'currency_id': order.currency_id.id,
            'company_id': order.company_id.id,
            'state': order.state,
            'amount_total': order.amount_total,
            'invoice_status': order.invoice_status,
            'amount_total': order.amount_total,
            'advance_payment_status': order.advance_payment_status
        }
    
    # methode pour reccuperer la liste des wave.transaction pour un partner
    @http.route('/api/payment/wave/partner-transactions<int:partner_id>', type='http', auth='public', cors='*', methods=['GET'], csrf=False)
    def get_wave_transactions_partner(self, partner_id):

        partner = request.env['res.partner'].sudo().browse(partner_id)
        if not partner.exists():
            return self._make_response(
                {
                    'success': False,
                    'error': 'Partenaire non trouvé'
                }, 404
            )
        
        wave_transactions = request.env['wave.transaction'].sudo().search([('partner_id', '=', partner_id)])
        resultat = []

        for transaction in wave_transactions:
            resultat.append({
                'transaction_id': transaction.transaction_id,
                'custom_transaction_id': transaction.transaction_id,
                'wave_id': transaction.wave_id,
                'session_id': transaction.wave_id,
                'reference': transaction.reference,
                'status': transaction.status,
                'checkout_status': transaction.checkout_status,
                'payment_status': transaction.payment_status,
                'amount': transaction.amount,
                'currency': transaction.currency,
                'phone': transaction.phone,
                'description': transaction.description,
                'created_at': transaction.created_at,
                'completed_at': transaction.completed_at,
                'order': self._order_to_dict(transaction.order_id)
            })
        return self._make_response(
            resultat, 200
        )


    
    # def _process_wave_webhook(self, webhook_data):
    #     """Traiter les données du webhook Wave"""
    #     try:
    #         event_type = webhook_data.get('type') or webhook_data.get('event')
    #         _logger.info(f"Processing event type: {event_type}")
    #         if event_type == "checkout.session.completed":
    #             session_data = webhook_data.get('data', {})
    #             session_id = session_data.get('id')
    #             if not session_id:
    #                 return {'error': 'Missing session ID in webhook data', 'success': False}
    #             # Rechercher la transaction
    #             transaction = request.env['wave.transaction'].sudo().search([('wave_id', '=', session_id)], limit=1)
    #             if not transaction:
    #                 _logger.warning(f"Transaction not found for Wave session ID: {session_id}")
    #                 return {'error': 'Transaction not found', 'success': False}
    #             # Vérifier checkout_status et payment_status
    #             checkout_status = session_data.get('checkout_status', '').lower()
    #             payment_status = session_data.get('payment_status', '').lower()
    #             new_status = self._map_wave_status_to_odoo(checkout_status, payment_status)
    #             if new_status:
    #                 _logger.info(f"Updating status from webhook for transaction {transaction.id} to {new_status}")
    #                 completed_at = session_data.get('when_completed')
    #                 if completed_at:
    #                     completed_at = self.convert_iso_format_to_custom_format(completed_at)

    #                 transaction.write({
    #                     'status': new_status,
    #                     'updated_at': fields.Datetime.now(),
    #                     'completed_at': completed_at,
    #                     'webhook_data': json.dumps(webhook_data),
    #                     'checkout_status': checkout_status,
    #                     'payment_status': payment_status,
    #                 })
    #                 # Déclencher des actions selon le statut
    #                 if new_status == 'completed':
    #                     # return {'success': True, 'transaction_updated': True, 'custom_transaction_id': transaction.transaction_id}
    #                     resultat = self._create_payment_without_invoice(transaction)
    #                     if resultat:
    #                         return {'success': True, 'transaction_updated': True, 'custom_transaction_id': transaction.transaction_id}
    #                     else:
    #                         return {'success': False, 'error': 'Failed to create payment transaction', 'custom_transaction_id': transaction.transaction_id}
    #                 elif new_status == 'failed':
    #                     return {'success': True, 'transaction_updated': False, 'custom_transaction_id': transaction.transaction_id}
                    

                    
    #         elif event_type == "checkout.session.payment_failed":
    #             _logger.error(f"Event type failed: {event_type}")
    #             return {'error': f"Event type failed: {event_type}", 'success': True}
    #         else:
    #             _logger.error(f"Unknown event type: {event_type}")
    #             return {'error': f"Unknown event type: {event_type}", 'success': True}
    #     except Exception as e:
    #         _logger.error(f"Error processing webhook data: {str(e)}")
    #         return {'error': f'Processing error: {str(e)}', 'success': True}

    # @http.route('/wave/webhook', type='http', auth='public', csrf=False, methods=['POST'])
    # def wave_webhook(self, **kwargs):
    #     """Gérer les webhooks Wave"""
    #     try:
    #         # Récupérer la configuration Wave
    #         config = request.env['wave.config'].sudo().search([('is_active', '=', True)], limit=1)
    #         if not config:
    #             _logger.error("Wave configuration not found for webhook")
    #             return Response(json.dumps({'error': 'Configuration not found'}), status=400, mimetype='application/json')
    #         # Récupérer les headers et le body
    #         headers = request.httprequest.headers
    #         body = request.httprequest.get_data()
    #         signature = headers.get('Wave-Signature')
    #         if signature is None:
    #             _logger.error("Invalid signature")
    #             return Response(json.dumps({'error': 'Invalid signature'}), status=400, mimetype='application/json')
    #         parts = signature.split(',')
    #         signatures = []
    #         timestamp = None
    #         for part in parts:
    #             key, value = part.split('=', 1)
    #             if key == 't':
    #                 timestamp = value
    #             elif key == 'v1':
    #                 signatures.append(value)
    #         if not timestamp or not signatures:
    #             _logger.error("Invalid signature")
    #             return Response(json.dumps({'error': 'Invalid signature'}), status=400, mimetype='application/json')
    #         # # Vérification de la signature Wave
    #         # if not self._verify_wave_signature(body, signatures, timestamp, config.webhook_secret):
    #         #     _logger.error("Invalid Wave webhook signature")
    #         #     return Response(json.dumps({'error': 'Invalid signature'}), status=400, mimetype='application/json')
    #         # Parser les données JSON
    #         try:
    #             webhook_data = json.loads(body.decode('utf-8'))
    #         except json.JSONDecodeError:
    #             _logger.error("Invalid JSON in webhook payload")
    #             # return Response(json.dumps({'error': 'Invalid JSON'}), status=400, mimetype='application/json')
    #             return Response(json.dumps(webhook_data), status=200, mimetype='application/json')
            
    #         # Traiter le webhook
    #         result = self._process_wave_webhook(webhook_data)
    #         if result.get('success'):
    #             return Response(json.dumps({'status': 'success'}), status=200, mimetype='application/json')
    #         else:
    #             return Response(json.dumps({'error': result.get('error', 'Processing failed')}), status=200, mimetype='application/json')
    #     except Exception as e:
    #         _logger.error(f"Error processing Wave webhook: {str(e)}")
    #         return Response(json.dumps({'error': 'Internal server error'}), status=200, mimetype='application/json')



    def convert_iso_format_to_custom_format(self , iso_date):
        try:
            # Parse the ISO format date
            dt = datetime.strptime(iso_date, "%Y-%m-%dT%H:%M:%SZ")
            # Convert to the desired format
            custom_format_date = dt.strftime("%Y-%m-%d %H:%M:%S")
            return custom_format_date
        except ValueError as e:
            _logger.error(f"Error converting date format: {str(e)}")
            return None




    def _create_payment_without_invoice(self, transaction):
        """Créer un paiement sans facture pour une transaction Orange Money réussie"""
        try:
            _logger.info(f"Début de la création du paiement et de la facture pour la transaction {transaction.transaction_id}")
            order = transaction.order_id
            partner = transaction.partner_id
            company = partner.company_id or request.env['res.company'].sudo().search([('id', '=', 1)], limit=1)
            _logger.info(f"Compagnie trouvée: {company.name}")

            journal = request.env['account.journal'].sudo().search([('code', '=', 'CSH1'), ('company_id', '=', company.id)], limit=1)
            if not journal:
                _logger.error("Aucun journal de vente trouvé pour la compagnie.")
                return False

            _logger.info(f"Journal trouvé: {journal.name}")

            payment_method = request.env['account.payment.method'].sudo().search([('payment_type', '=', 'inbound')], limit=1)
            if not payment_method:
                _logger.error("Aucune méthode de paiement trouvée.")
                return False

            _logger.info(f"Méthode de paiement trouvée: {payment_method.name}")

            payment_method_line = request.env['account.payment.method.line'].sudo().search([
                ('payment_method_id', '=', payment_method.id),
                ('journal_id', '=', journal.id)
            ], limit=1)
            if not payment_method_line:
                _logger.error("Aucune ligne de méthode de paiement trouvée.")
                return False

            _logger.info(f"Ligne de méthode de paiement trouvée: {payment_method_line.id}")

            if order and order.state not in ['sale', 'done']:
                _logger.info(f"Confirmation de la commande {order.name}")
                order.action_confirm()


            currency_id = partner.currency_id.id or order.currency_id.id or journal.currency_id.id
            if not currency_id:
                _logger.error("Aucune devise trouvée pour la facture.")
                return False


            if order.amount_residual > 0:
                _logger.info(f"Création du paiement pour la commande {order.name}")
                account_payment = request.env['account.payment'].sudo().create({
                    'payment_type': 'inbound',
                    'partner_type': 'customer',
                    'partner_id': partner.id,
                    'amount': transaction.amount,
                    'journal_id': journal.id,
                    'currency_id': currency_id,
                    'payment_method_line_id': payment_method_line.id,
                    'payment_method_id': payment_method.id,
                    'ref': order.name,
                    'sale_id': order.id,
                    'is_reconciled': True,
                    'destination_account_id': partner.property_account_receivable_id.id,
                })
                account_payment.action_post()
                _logger.info(f"Paiement créé et validé pour la commande {order.name}")
            else:
                _logger.warning(f"Le montant résiduel de la commande {order.name} est de 0, aucun paiement créé.")

            _logger.info(f"Paiement et facture créés avec succès pour la transaction Orange Money {transaction.transaction_id}")
            return True
        except Exception as e:
            _logger.error(f"Erreur lors de la création du paiement Orange Money: {str(e)}")
            return False


    def _create_payment_transaction(self, transaction):
        try:
            order = transaction.order_id
            partner = transaction.partner_id
            company = partner.company_id

            # Rechercher un journal de vente
            journal = request.env['account.journal'].sudo().search([
                ('type', '=', 'sale'),  # Assurez-vous que le journal est de type vente
                ('company_id', '=', company.id)
            ], limit=1)

            if not journal:
                return False

            payment_method = request.env['account.payment.method'].sudo().search([('payment_type', '=', 'inbound')], limit=1)
            payment_method_line = request.env['account.payment.method.line'].sudo().search([
                ('payment_method_id', '=', payment_method.id),
                ('journal_id', '=', journal.id)
            ], limit=1)

            if not company:
                company = request.env['res.company'].sudo().search([('id', '=', 1)], limit=1)

            if order and order.state != 'sale':
                order.action_confirm()

            invoice_lines = []
            for line in order.order_line:
                invoice_lines.append((0, 0, {
                    'name': line.name,
                    'quantity': line.product_uom_qty,
                    'price_unit': line.price_unit,
                    'product_id': line.product_id.id,
                    'tax_ids': [(6, 0, line.tax_id.ids)],
                }))
            pourcentage = transaction.amount * 100 / order.amount_total

            invoice = request.env['account.move'].sudo().create({
                'partner_id': partner.id,
                'move_type': 'out_invoice',
                'invoice_date': transaction.created_at,
                'invoice_date_due': transaction.completed_at,
                'currency_id': partner.currency_id.id or order.currency_id.id or journal.currency_id.id,
                'journal_id': journal.id,
                'invoice_line_ids': invoice_lines,
                'invoice_origin': order.name,
                'company_id': company.id,
                'percentage_of_payment': pourcentage
            })

            invoice.action_post()
            order.write({
                'invoice_ids': [(4, invoice.id)]
            })

            if invoice:
                payment = request.env['account.payment'].sudo().create({
                    'payment_type': 'inbound',
                    'partner_type': 'customer',
                    'partner_id': partner.id,
                    'amount': transaction.amount,
                    'journal_id': journal.id,
                    'currency_id': partner.currency_id.id or order.currency_id.id or journal.currency_id.id,
                    'payment_method_line_id': payment_method_line.id,
                    'payment_method_id': payment_method.id,
                    'ref': order.name,
                    'destination_account_id': partner.property_account_receivable_id.id,
                })

                if payment:
                    payment.action_post()
                    # order.write({
                    #     'invoice_ids': [(4, invoice.id)],
                    # })

                    # invoice.js_assign_outstanding_line(payment.line_ids[0].id)
                    return True
                else:
                    return False
            else:
                return False

        except Exception as e:
            _logger.error("Erreur lors de la création du paiement: %s", str(e))
            return False
        
    # liste des transaction d'un partenaire

    @http.route('/api/payment/partner/<int:partner_id>/transactions', type='http', auth='public', cors='*', methods=['GET'])
    def get_partner_transactions(self, partner_id):
        try:
            partner = request.env['res.partner'].sudo().search([('id', '=', partner_id)])
            if not partner:
                return self._make_response({'success': False, 'error': 'Partner not found'}, 404)

            resultats = []
            transactions = request.env['wave.transaction'].sudo().search([('partner_id', '=', partner_id)])

            for transaction_up in transactions:
                # Convertir les données binaires en base64
                facture_pdf_base64 = None
                if transaction_up.facture_pdf:
                    facture_pdf_base64 = base64.b64encode(transaction_up.facture_pdf).decode('utf-8')

                resultats.append({
                    'transaction_id': transaction_up.transaction_id,
                    'custom_transaction_id': transaction_up.transaction_id,
                    'wave_id': transaction_up.wave_id,
                    'session_id': transaction_up.wave_id,
                    'reference': transaction_up.reference,
                    'status': transaction_up.status,
                    'checkout_status': transaction_up.checkout_status,
                    'payment_status': transaction_up.payment_status,
                    'amount': transaction_up.amount,
                    'currency': transaction_up.currency,
                    'phone': transaction_up.phone,
                    'description': transaction_up.description,
                    'payment_url': transaction_up.payment_link_url,
                    'order_id': transaction_up.order_id.id,
                    'order_type': transaction_up.order_id.type_sale,
                    'order': self._order_to_dict(transaction_up.order_id),
                    'type_sale': transaction_up.order_id.type_sale,
                    'partner_id': transaction_up.partner_id.id,
                    'created_at': transaction_up.created_at.isoformat(),
                    'updated_at': transaction_up.updated_at.isoformat(),
                    'completed_at': transaction_up.completed_at.isoformat() if transaction_up.completed_at else None,
                    # 'facture_pdf': facture_pdf_base64,
                    'url_facture': transaction_up.url_facture
                })

            return Response(json.dumps(resultats), status=200, mimetype='application/json')

        except Exception as e:
            return Response(json.dumps({'success': False, 'error': str(e)}), status=400, mimetype='application/json')