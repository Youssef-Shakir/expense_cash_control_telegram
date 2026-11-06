# -*- coding: utf-8 -*-
"""Owner App (PWA): /ecc/owner/app on the phone, installable ("Add to Home screen").

Page, manifest and service worker are public files; every API call needs a logged-in user linked to the
box (``ecc.owner.box.app_user_id``). Writes go through the same box methods as the Telegram bot.
"""
import base64
import binascii
import json
import logging
import re
from pathlib import Path

import psycopg2

from odoo import _, http
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.http import request
from odoo.tools import float_round

_logger = logging.getLogger(__name__)

STATIC = Path(__file__).resolve().parent.parent / 'static' / 'owner_app'
ASSET_URL = '/expense_cash_control_telegram/static/owner_app'
UID_RE = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 8 * 1024 * 1024
WRITE_ACTIONS = ('collect', 'expense', 'took', 'deposit', 'count', 'statement_answer')


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
        except (UserError, ValidationError) as e:
            return {'ok': False, 'code': 'refused', 'error': e.args[0] if e.args else str(e)}
        except (AccessError, AccessDenied):
            return {'ok': False, 'code': 'forbidden', 'error': _('Not allowed.')}
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

    def _amount(self, box, value, allow_none=False):
        if value in (None, '') and allow_none:
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise AppError(_('Enter a valid amount.')) from None
        amount = float_round(amount, precision_rounding=box.currency_id.rounding)
        if amount <= 0:
            raise AppError(_('The amount must be positive.'))
        return amount

    def _note(self, note):
        return (note or '').strip()[:500] or None

    def _request_uid(self, request_uid):
        if request_uid and UID_RE.match(str(request_uid)):
            return str(request_uid)
        return None

    def _done(self, box, move, text, **extra):
        return dict(extra, card=box._api_card(), text=text, move_id=move.id if move else False)

    def _replay(self, box, request_uid):
        """The same action sent again (no answer reached the phone): answer with what is saved."""
        if not request_uid:
            return None
        move = request.env['ecc.owner.move'].sudo().search(
            [('box_id', '=', box.id), ('app_request_uid', '=', request_uid)], limit=1)
        if move:
            return self._done(box, move, _('Already saved: %(name)s · %(amount)s', name=move.name,
                                          amount=box.currency_id.format(move.amount)), replayed=True)
        return None

    def _stamp(self, move, request_uid):
        if request_uid:
            move.sudo().app_request_uid = request_uid

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

    # writing ----------------------------------------------------------

    def _api_collect(self, box_id, session_id, amount=None, request_uid=None):
        box = self._box(box_id)
        request_uid = self._request_uid(request_uid)
        replay = self._replay(box, request_uid)
        if replay:
            return replay
        session = request.env['pos.session'].sudo().browse(int(session_id or 0)).exists()
        if not session:
            raise AppError(_('Session not found.'), 'not_found')
        move = box._collect_session(session, self._amount(box, amount, allow_none=True), source='app')
        self._stamp(move, request_uid)
        return self._done(box, move, _('Collected %(amount)s from %(session)s', amount=box.currency_id.format(
            move.amount), session=session.name), sessions=box._api_sessions(30))

    def _api_expense(self, box_id, amount, category_id, note=None, photos=None, request_uid=None):
        box = self._box(box_id)
        request_uid = self._request_uid(request_uid)
        replay = self._replay(box, request_uid)
        if replay:
            return replay
        amount = self._amount(box, amount)
        category = box._api_category(category_id)
        if not category:
            raise AppError(_('Choose a category.'))
        decoded = []
        for index, photo in enumerate((photos or [])[:MAX_PHOTOS]):
            try:
                content = base64.b64decode((photo or {}).get('content_b64') or '', validate=True)
            except (binascii.Error, ValueError, AttributeError):
                raise AppError(_('A photo could not be read. Take it again.')) from None
            if not content or len(content) > MAX_PHOTO_BYTES:
                raise AppError(_('A photo is too large.'))
            mimetype = photo.get('mimetype') or 'image/jpeg'
            if not mimetype.startswith('image/'):
                raise AppError(_('Only photos can be attached.'))
            decoded.append({'content': content, 'mimetype': mimetype,
                            'filename': (photo.get('filename') or 'receipt-%s.jpg' % (index + 1))[:200]})
        move, receipt = box._record_expense(amount, category, note=self._note(note), photos=decoded, source='app')
        self._stamp(move, request_uid)
        return self._done(box, move, _('Expense %(amount)s (%(category)s) recorded · waiting for accountant '
                                       'review', amount=box.currency_id.format(amount), category=category.name),
                          reference=receipt.name)

    def _api_took(self, box_id, amount, note=None, request_uid=None):
        box = self._box(box_id)
        request_uid = self._request_uid(request_uid)
        replay = self._replay(box, request_uid)
        if replay:
            return replay
        move = box._record_drawing(self._amount(box, amount), self._note(note), source='app')
        self._stamp(move, request_uid)
        return self._done(box, move, _('Took %s for you', box.currency_id.format(-move.amount)))

    def _api_deposit(self, box_id, amount, target, note=None, request_uid=None):
        box = self._box(box_id)
        if target not in ('bank', 'till'):
            raise AppError(_('Choose bank or till.'))
        request_uid = self._request_uid(request_uid)
        replay = self._replay(box, request_uid)
        if replay:
            return replay
        move = box._record_deposit(self._amount(box, amount), target, self._note(note), source='app')
        self._stamp(move, request_uid)
        return self._done(box, move, _('Deposited %s', box.currency_id.format(-move.amount)))

    def _api_count(self, box_id, counted):
        box = self._box(box_id)
        try:
            counted = float_round(float(counted), precision_rounding=box.currency_id.rounding)
        except (TypeError, ValueError):
            raise AppError(_('Enter a valid amount.')) from None
        if counted < 0:
            raise AppError(_('The amount cannot be negative.'))
        expected = box.balance
        difference = box._record_count(counted)
        fmt = box.currency_id.format
        if difference:
            text = _('You counted %(counted)s, the books say %(expected)s (difference %(difference)s). '
                     'The accountant will check it.', counted=fmt(counted), expected=fmt(expected),
                     difference=fmt(difference.amount))
        else:
            text = _('%s — it matches the books.', fmt(counted))
        return self._done(box, None, text, difference=difference.amount if difference else 0.0,
                          expected=expected)

    def _api_statement_answer(self, box_id, statement_id, correct, note=None):
        box = self._box(box_id)
        statement = request.env['ecc.owner.statement'].sudo().browse(int(statement_id or 0)).exists()
        if not statement or statement.box_id != box:
            raise AppError(_('Statement not found.'), 'not_found')
        if statement.state not in ('draft', 'sent'):
            raise AppError(_('This statement was already answered.'))
        statement._answer(bool(correct), self._note(note))
        text = _('Thank you, statement confirmed.') if correct else \
            _('Noted. The accountant will check the statement with you.')
        return self._done(box, None, text, statements=box._api_statements())
