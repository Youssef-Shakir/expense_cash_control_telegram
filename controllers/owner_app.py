# -*- coding: utf-8 -*-
"""Owner App (PWA): /ecc/owner/app on the phone, installable ("Add to Home screen").

Page, manifest and service worker are public files; every API call needs a logged-in user linked to the
box (``ecc.owner.box.app_user_id``). Writes go through the same box methods as the Telegram bot.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

from odoo import _, http
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.http import request

from ..models.owner_service import OwnerServiceError

_logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent.parent / 'static' / 'owner_app'
ASSET_URL = '/expense_cash_control_telegram/static/owner_app'
WRITE_ACTIONS = ('collect', 'expense', 'took', 'deposit', 'count', 'statement_answer',
                 'card_withdraw', 'card_expense', 'card_count', 'notifications_set')


class AppError(Exception):
    """A refusal shown to the owner as is."""

    def __init__(self, message, code='refused'):
        super().__init__(message)
        self.code = code


class OwnerApp(http.Controller):

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    @http.route(['/ecc/owner', '/ecc/owner/'], type='http', auth='public', sitemap=False)
    def owner_root(self, **kw):
        return request.redirect('/ecc/owner/app', 303)

    @http.route('/ecc/owner/app', type='http', auth='public', sitemap=False)
    def owner_app(self, **kw):
        version = request.env['ir.module.module'].sudo().search(
            [('name', '=', 'expense_cash_control_telegram')], limit=1).latest_version or '1'
        html = (STATIC / 'index.html').read_text(encoding='utf-8')
        html = html.replace('{{ASSET}}', ASSET_URL).replace('{{VERSION}}', version)
        return request.make_response(html, headers=[
            ('Content-Type', 'text/html; charset=utf-8'),
            ('Cache-Control', 'no-cache'),
            ('X-Frame-Options', 'DENY'),
        ])

    @http.route('/ecc/owner/manifest.webmanifest', type='http', auth='public', sitemap=False)
    def owner_manifest(self, **kw):
        manifest = {
            'name': _('Owner Cash Box') + ' · DoniaLink',
            'short_name': _('Cash Box'),
            'description': _('Collect POS cash, record expenses and see your balance.'),
            'developer': {'name': 'DoniaLink · Yousif Shakir', 'url': 'https://www.donialink.com'},
            'id': '/ecc/owner/app',
            'start_url': '/ecc/owner/app',
            'scope': '/ecc/owner/',
            'display': 'standalone',
            'orientation': 'portrait',
            'background_color': '#0a1622',
            'theme_color': '#0a1622',
            'lang': 'ar',
            'dir': 'auto',
            'icons': [
                {'src': f'{ASSET_URL}/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                {'src': f'{ASSET_URL}/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
                {'src': f'{ASSET_URL}/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png',
                 'purpose': 'maskable'},
            ],
        }
        return request.make_response(json.dumps(manifest, ensure_ascii=False), headers=[
            ('Content-Type', 'application/manifest+json; charset=utf-8'), ('Cache-Control', 'no-cache')])

    @http.route('/ecc/owner/sw.js', type='http', auth='public', sitemap=False)
    def owner_service_worker(self, **kw):
        version = request.env['ir.module.module'].sudo().search(
            [('name', '=', 'expense_cash_control_telegram')], limit=1).latest_version or '1'
        js = (STATIC / 'sw.js').read_text(encoding='utf-8')
        js = js.replace('{{ASSET}}', ASSET_URL).replace('{{VERSION}}', version)
        return request.make_response(js, headers=[
            ('Content-Type', 'application/javascript; charset=utf-8'),
            ('Cache-Control', 'no-cache'),
            ('Service-Worker-Allowed', '/ecc/owner/'),
        ])

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    @http.route('/ecc/owner/api/<string:action>', type='json', auth='public', methods=['POST'], csrf=False,
                sitemap=False)
    def owner_api(self, action, **params):
        handler = getattr(self, '_api_%s' % action, None)
        if not handler or action.startswith('_'):
            return {'ok': False, 'code': 'not_found', 'error': 'Unknown action'}
        if action not in ('session', 'login') and request.env.user._is_public():
            return {'ok': False, 'code': 'login', 'error': _('Please log in.')}
        try:
            if action in WRITE_ACTIONS:
                # a refused action leaves nothing half-written (login commits itself: no savepoint there)
                with request.env.cr.savepoint():
                    result = handler(**params)
            else:
                result = handler(**params)
        except AppError as e:
            return {'ok': False, 'code': e.code, 'error': str(e)}
        except OwnerServiceError as e:
            return {'ok': False, 'code': e.code, 'error': e.args[0] if e.args else str(e)}
        except (AccessError, AccessDenied):
            # before UserError: AccessError is one
            return {'ok': False, 'code': 'forbidden', 'error': _('Not allowed.')}
        except (UserError, ValidationError) as e:
            return {'ok': False, 'code': 'refused', 'error': e.args[0] if e.args else str(e)}
        except psycopg2.IntegrityError:
            # two identical requests at the same time: the other one saved it
            return {'ok': False, 'code': 'duplicate', 'error': _('Already saved. Refresh to see it.')}
        except TypeError as e:
            _logger.info('Owner app: bad parameters for %s: %s', action, e)
            return {'ok': False, 'code': 'bad_request', 'error': _('Invalid request.')}
        result = result or {}
        result.setdefault('ok', True)
        return result

    # helpers ----------------------------------------------------------

    def _box(self, box_id):
        try:
            box_id = int(box_id)
        except (TypeError, ValueError):
            raise AppError(_('Choose a cash box.'), 'not_found') from None
        boxes = request.env['ecc.owner.box']._app_boxes()
        box = boxes.filtered(lambda b: b.id == box_id)
        if not box:
            raise AppError(_('This cash box is not yours.'), 'forbidden')
        return box.with_company(box.company_id).with_context(lang=request.env.user.lang)

    def _svc(self):
        return request.env['ecc.owner.service'].with_context(ecc_source='app', lang=request.env.user.lang)

    def _card(self, box, card_id):
        return self._svc()._card(box, card_id)

    # session ----------------------------------------------------------

    def _user_info(self):
        user = request.env.user
        boxes = request.env['ecc.owner.box']._app_boxes(user)
        return {
            'logged': True,
            'user': user.name,
            'lang': (user.lang or 'en_US')[:2],
            'boxes': [box.with_company(box.company_id)._api_card() for box in boxes],
        }

    def _api_session(self):
        if request.env.user._is_public():
            return {'logged': False, 'db': bool(request.db)}
        return self._user_info()

    def _api_login(self, login, password):
        if not request.db:
            raise AppError(_('Open the Odoo login page once to choose the database.'), 'no_db')
        try:
            request.session.authenticate(request.db, {'login': (login or '').strip(), 'password': password or '',
                                                      'type': 'password'})
        except AccessDenied:
            raise AppError(_('Wrong login or password.'), 'login') from None
        if not request.session.uid:
            raise AppError(_('Two-factor login is on for this user: log in from the Odoo page.'), 'mfa')
        info = self._user_info()
        if not info['boxes']:
            request.session.logout(keep_db=True)
            raise AppError(_('No cash box is linked to this login. Ask the accountant.'), 'no_box')
        return info

    def _api_logout(self):
        request.session.logout(keep_db=True)
        return {'logged': False}

    # reading ----------------------------------------------------------

    def _api_home(self, box_id):
        box = self._box(box_id)
        return {
            'card': box._api_card(),
            'sessions': box._api_sessions(30),
            'pending_statements': len(box.statement_ids.filtered(lambda s: s.state == 'sent')),
        }

    def _api_categories(self, box_id):
        return {'categories': self._box(box_id)._api_categories()}

    def _api_moves(self, box_id, limit=30):
        box = self._box(box_id)
        rows, _lines = box._api_moves(min(max(int(limit or 30), 1), 100))
        return {'moves': rows, 'card': box._api_card()}

    def _api_statements(self, box_id):
        box = self._box(box_id)
        return {'statements': box._api_statements(), 'card': box._api_card()}

    # writing (same service as the connector tools) ---------------------

    def _api_collect(self, box_id, session_id, amount=None, request_uid=None):
        return self._svc().collect(self._box(box_id), session_id, amount, request_uid)

    def _api_expense(self, box_id, amount, category_id, note=None, photos=None, request_uid=None):
        return self._svc().expense(self._box(box_id), amount, category_id, note, photos, request_uid)

    def _api_took(self, box_id, amount, note=None, request_uid=None):
        return self._svc().took(self._box(box_id), amount, note, request_uid)

    def _api_deposit(self, box_id, amount, target, note=None, request_uid=None, card_id=None):
        return self._svc().deposit(self._box(box_id), amount, target, note, request_uid, card_id)

    def _api_count(self, box_id, counted):
        return self._svc().count(self._box(box_id), counted)

    def _api_notifications(self, box_id):
        return self._svc().notifications(self._box(box_id))

    def _api_notifications_set(self, box_id, **values):
        allowed = {'session_closed', 'reminder_expense', 'reminder_count_weekday', 'reminder_hour'}
        return self._svc().set_notifications(self._box(box_id), **{k: v for k, v in values.items() if k in allowed})

    def _api_statement_answer(self, box_id, statement_id, correct, note=None):
        return self._svc().statement_answer(self._box(box_id), statement_id, correct, note)

    # cards ------------------------------------------------------------

    def _api_card_home(self, box_id, card_id, limit=30):
        return self._svc().card_home(self._box(box_id), card_id, limit)

    def _api_card_withdraw(self, box_id, card_id, amount, target='box', note=None, request_uid=None):
        return self._svc().card_withdraw(self._box(box_id), card_id, amount, target, note, request_uid)

    def _api_card_expense(self, box_id, card_id, amount, category_id, note=None, photos=None, request_uid=None):
        return self._svc().card_expense(self._box(box_id), card_id, amount, category_id, note, photos, request_uid)

    def _api_card_count(self, box_id, card_id, counted):
        return self._svc().card_count(self._box(box_id), card_id, counted)

    # push notifications --------------------------------------------------

    def _api_push_key(self):
        return {'key': request.env['mail.push.device'].sudo().get_web_push_vapid_public_key()}

    def _api_push_subscribe(self, endpoint, keys, vapid_key, expiration=None):
        """This phone gets the notifications of the logged-in owner (one phone = one login)."""
        if not request.env['ecc.owner.box']._app_boxes():
            raise AccessError('no box')
        if not isinstance(endpoint, str) or not endpoint.startswith('https://') or len(endpoint) > 2048 \
                or not isinstance(keys, dict) or not keys.get('p256dh') or not keys.get('auth'):
            raise AppError(_('Invalid request.'), 'bad_request')
        Device = request.env['mail.push.device'].sudo()
        if vapid_key != Device.get_web_push_vapid_public_key():
            raise AppError(_('The server key changed. Turn notifications on again.'), 'push_key')
        partner = request.env.user.partner_id
        expiration = None if not isinstance(expiration, (int, float)) else \
            datetime.fromtimestamp(expiration / 1000, tz=timezone.utc).replace(tzinfo=None)
        values = {'partner_id': partner.id, 'keys': json.dumps({'p256dh': str(keys['p256dh']),
                                                                'auth': str(keys['auth'])}),
                  'expiration_time': expiration}
        device = Device.search([('endpoint', '=', endpoint)], limit=1)
        if device:
            device.write(values)
        else:
            Device.create(dict(values, endpoint=endpoint))
        return {'push': True}

    def _api_push_unsubscribe(self, endpoint):
        request.env['mail.push.device'].sudo().search(
            [('endpoint', '=', endpoint), ('partner_id', '=', request.env.user.partner_id.id)]).unlink()
        return {'push': False}
