# -*- coding: utf-8 -*-
"""Owner App: the same owner cash box as the Telegram bot, in an installable web app (PWA) served by Odoo at
/ecc/owner/app. The owner logs in with an Odoo login (a free portal user is enough) linked to his box.

The bot tools (agent_tools_owner) and the app controller share the data builders below, so both channels show
the same card, sessions, categories, moves and statements, and record through the same box methods.
"""
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OwnerBoxApp(models.Model):
    _inherit = 'ecc.owner.box'

    app_user_id = fields.Many2one('res.users', string='Owner App Login', copy=False, tracking=True, index=True,
                                  help='This login opens the owner app (/ecc/owner/app) on this cash box.')
    app_url = fields.Char('Owner App', compute='_compute_app_url')
    platform_enabled = fields.Boolean(
        'On DoniaLink App', copy=False, tracking=True,
        help='Set by the DoniaLink Platform when a platform user may open this box. Its notifications are then '
             'sent to the platform even without a Telegram link.')
    app_push_count = fields.Integer('Phones with Notifications', compute='_compute_app_push_count',
                                    help='Phones where the owner turned notifications on in the app (menu ☰).')

    def _compute_app_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for box in self:
            box.app_url = '%s/ecc/owner/app' % base.rstrip('/')

    def _compute_app_push_count(self):
        for box in self:
            box.app_push_count = len(box._app_devices()) if box.id else 0

    def _app_card(self, card_id):
        """A card shared with this box (the owner app), or an empty record."""
        self.ensure_one()
        try:
            card_id = int(card_id)
        except (TypeError, ValueError):
            return self.env['ecc.owner.card']
        return self.sudo().card_ids.filtered(lambda c: c.id == card_id and c.active)

    # ------------------------------------------------------------------
    # Push notifications (Web Push through Odoo's mail.push queue)
    # ------------------------------------------------------------------

    def _app_lang(self):
        self.ensure_one()
        box = self.sudo()
        return box.app_user_id.lang or box.company_id.partner_id.lang or self.env.lang

    def _owner_notify(self, kind, text, title, body=None, route='home', card=None, tag=None, data=None,
                      raise_errors=False):
        """One notification to the owner on every channel he uses: Web Push of the Odoo owner app, and the
        DoniaLink Platform (its app and/or Telegram) when the box is linked to Telegram or on the platform.
        Returns (platform answer or {}, number of phones pushed). Errors are logged, except with
        ``raise_errors`` (statements: the caller records that it was not sent)."""
        self.ensure_one()
        box = self.sudo()
        pushed = box._app_push(title, body or text, route=route, card=card, tag=tag) if box.app_user_id else 0
        answer = {}
        if box.telegram_user_id or box.platform_enabled:
            payload = dict(data or {}, title=title, body=body or text, route=route,
                           card_id=card.id if card else None, tag=tag)
            try:
                answer = box._platform_send(kind, text, payload) or {}
            except Exception as e:  # noqa: BLE001 - a notification never stops the action that sent it
                if raise_errors:
                    raise
                _logger.warning('Owner cash box %s: %s notification not sent: %s', box.name, kind, e)
        return answer, pushed

    def _app_devices(self):
        self.ensure_one()
        user = self.sudo().app_user_id
        if not user:
            return self.env['mail.push.device']
        return self.env['mail.push.device'].sudo().search([('partner_id', '=', user.partner_id.id)])

    def _app_push(self, title, body, route='home', card=None, tag=None):
        """Queue a notification to the phones where the owner turned notifications on. Never raises: a
        notification must not stop the action that sent it. Tapping it opens the app on ``route`` (and the
        ``card``) of this box. Returns the number of phones."""
        self.ensure_one()
        url = '/ecc/owner/app?box=%s%s#%s' % (self.id, '&card=%s' % card.id if card else '', route)
        try:
            devices = self._app_devices()
            if not devices:
                return 0
            payload = json.dumps({
                'title': title[:120],
                'options': {
                    'body': (body or '')[:400],
                    'icon': '/expense_cash_control_telegram/static/owner_app/icon-192.png',
                    'badge': '/expense_cash_control_telegram/static/owner_app/favicon-32.png',
                    'tag': tag or False,
                    'data': {'url': url, 'box_id': self.id},
                },
            }, ensure_ascii=False)
            self.env['mail.push'].sudo().create([{'mail_push_device_id': d.id, 'payload': payload}
                                                 for d in devices])
            cron = self.env.ref('mail.ir_cron_web_push_notification', raise_if_not_found=False)
            if cron:
                cron.sudo()._trigger()
            return len(devices)
        except Exception as e:  # noqa: BLE001
            _logger.warning('Owner app: push notification to %s not queued: %s', self.display_name, e)
            return 0

    @api.model
    def _app_boxes(self, user=None):
        user = user or self.env.user
        if not user or user._is_public():
            return self.browse()
        return self.sudo().search([('app_user_id', '=', user.id), ('active', '=', True)])

    def action_app_access(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Owner App Access'),
            'res_model': 'ecc.owner.app.access', 'view_mode': 'form', 'target': 'new',
            'context': {'ecc_owner_box_id': self.id},
        }

    def action_revoke_app(self):
        for box in self:
            box.message_post(body=_('Owner app access removed for %s.', box.app_user_id.name or ''))
        self.write({'app_user_id': False})
        return True

    # ------------------------------------------------------------------
    # Data shared by the bot tools and the app
    # ------------------------------------------------------------------

    def _api_card(self):
        self.ensure_one()
        box = self.sudo().with_company(self.company_id)
        box.invalidate_recordset(['balance', 'uncollected_session_count', 'uncollected_amount'])
        currency = box.currency_id
        return {
            'box_id': box.id,
            'owner': box.name,
            'company_id': box.company_id.id,
            'company': box.company_id.name,
            'currency': currency.name,
            'currency_symbol': currency.symbol,
            'decimals': currency.decimal_places,
            'balance': box.balance,
            'balance_text': currency.format(box.balance),
            'business_owes_owner': -box.balance if box.balance < 0 else 0.0,
            'uncollected_sessions': box.uncollected_session_count,
            'uncollected_amount': box.uncollected_amount,
            'uncollected_text': currency.format(box.uncollected_amount),
            'till_available': bool(box.till_journal_id),
            'till_name': box.till_journal_id.name or '',
            'bank_name': box.bank_journal_id.name or '',
            'text': box._card_text(),
            'cards': [card._api_summary() for card in box.card_ids.filtered('active')],
        }

    def _api_sessions(self, limit=10):
        self.ensure_one()
        currency = self.currency_id
        sessions = []
        for session in self._uncollected_sessions()[:limit]:
            stop = fields.Datetime.context_timestamp(session, session.stop_at) if session.stop_at else None
            sessions.append({
                'session_id': session.id,
                'name': session.name,
                'pos': session.config_id.name,
                'closed_at': stop.strftime('%Y-%m-%d %H:%M') if stop else None,
                'amount': session.owner_remaining_amount,
                'amount_text': currency.format(session.owner_remaining_amount),
                'state': session.owner_collection_state,
            })
        return sessions

    def _api_categories(self):
        self.ensure_one()
        Category = self.env['expense.category'].sudo()
        domain = [('company_id', 'in', [False, self.company_id.id]), ('owner_box_id', '=', False),
                  ('account_id', '!=', False)]
        categories = Category.search(domain + [('owner_expense', '=', True)], order='sequence, name') \
            or Category.search(domain, order='sequence, name')
        return [{'id': c.id, 'name': c.name} for c in categories]

    def _api_category(self, category_id):
        self.ensure_one()
        category = self.env['expense.category'].sudo().browse(int(category_id or 0)).exists()
        if not category or category.company_id not in (self.company_id, self.env['res.company']):
            return category.browse()
        return category

    def _api_moves(self, limit=10):
        self.ensure_one()
        moves = self.env['ecc.owner.move'].sudo().search(
            [('box_id', '=', self.id), ('state', '=', 'posted')], limit=limit)
        running = self.balance
        rows, lines = [], []
        currency = self.currency_id
        for move in moves:
            local = fields.Datetime.context_timestamp(move, move.date)
            rows.append({'id': move.id, 'date': fields.Datetime.to_string(move.date),
                         'local_date': local.strftime('%d/%m/%Y %H:%M'), 'type': move.kind,
                         'type_label': move._kind_label(), 'description': move.name, 'amount': move.amount,
                         'amount_text': currency.format(move.amount), 'balance_after': running,
                         'balance_after_text': currency.format(running), 'source': move.source,
                         'review': move.review_state or False})
            lines.append(move._bot_line(running))
            running -= move.amount
        return rows, lines

    def _api_statements(self, limit=12):
        self.ensure_one()
        fmt = self.currency_id.format
        result = []
        for statement in self.statement_ids[:limit]:
            result.append({
                'id': statement.id,
                'date_from': statement.date_from.strftime('%d/%m/%Y'),
                'date_to': statement.date_to.strftime('%d/%m/%Y'),
                'state': statement.state,
                'can_answer': statement.state in ('draft', 'sent'),
                'figures': [[key, getattr(statement, key), fmt(getattr(statement, key))] for key in
                            ('opening', 'collected', 'from_card', 'spent', 'took', 'deposited', 'adjusted',
                             'closing')],
                'closing': statement.closing,
                'answer_note': statement.answer_note or '',
            })
        return result


class OwnerMoveApp(models.Model):
    _inherit = 'ecc.owner.move'

    source = fields.Selection(selection_add=[('app', 'Owner App'), ('platform', 'DoniaLink App')],
                              ondelete={'app': 'set default', 'platform': 'set default'})
    app_request_uid = fields.Char('App Request', copy=False, index='btree_not_null', readonly=True,
                                  help='Sent by the owner app with each action: a retry on a bad connection '
                                       'returns the movement already saved instead of a second one.')

    _sql_constraints = [
        ('app_request_uid_unique', 'unique(box_id, app_request_uid)', 'This app action was already recorded.'),
    ]


class OwnerStatementApp(models.Model):
    _inherit = 'ecc.owner.statement'

    def _send(self):
        """Owners with the app see their statement there; the bot gets it too when he is linked."""
        app_only = self.filtered(lambda s: s.box_id.app_user_id and not s.box_id.telegram_user_id)
        for statement in self - app_only:
            if not statement.box_id.app_user_id:
                super(OwnerStatementApp, statement)._send()
                continue
            try:
                super(OwnerStatementApp, statement)._send()
            except UserError as e:
                statement.message_post(body=_('Not sent on Telegram: %s', e.args[0] if e.args else e))
            if statement.state == 'draft':
                statement.state = 'sent'   # waiting for him in the app
        app_only.write({'state': 'sent'})
        return True
