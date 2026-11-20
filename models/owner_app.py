# -*- coding: utf-8 -*-
"""Owner App: the owner cash box on the phone: the "Cash box" screen of the DoniaLink App
(/dl/app#cashbox, which replaced the owner app at /ecc/owner/app). The owner logs in with an Odoo login (a free
portal user is enough) linked to his box.

The app controller and the notifications use the data builders below (card, sessions, categories, moves and
statements); writes go through the same box methods.
"""
import json
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

DL_APP_SCREEN = 'cashbox'
# owner app routes (the ``route`` of the notifications) -> pages of the cash box screen of the DoniaLink App
DL_APP_ROUTES = {
    'home': [], 'collect': ['collect'], 'expense': ['expense'], 'took': ['took'], 'deposit': ['deposit'],
    'count': ['count'], 'moves': ['moves'], 'statements': ['statements'], 'notifications': ['notifications'],
    'bankcard': ['card'], 'cardwithdraw': ['card', 'withdraw'], 'cardexpense': ['card', 'expense'],
    'cardcount': ['card', 'count'], 'carddeposit': ['card', 'deposit'],
}


def _record_id(value):
    """A record or a number (from an address): its id, or 0."""
    if isinstance(value, models.BaseModel):
        return value.id if len(value) == 1 else 0
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


class OwnerBoxApp(models.Model):
    _inherit = 'ecc.owner.box'

    app_user_id = fields.Many2one('res.users', string='Owner App Login', copy=False, tracking=True, index=True,
                                  help='This login opens the cash box in the DoniaLink App (/dl/app#cashbox).')
    app_url = fields.Char('Owner App', compute='_compute_app_url')
    platform_enabled = fields.Boolean(
        'On the DoniaLink Platform', copy=False,
        help='Set by the old DoniaLink Platform owner app. Not used any more: the owner uses the DoniaLink App '
             '(/dl/app#cashbox).')
    app_push_count = fields.Integer('Phones with Notifications', compute='_compute_app_push_count',
                                    help='Phones where the owner turned notifications on in the app.')

    def _compute_app_url(self):
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        for box in self:
            box.app_url = '%s/dl/app' % base.rstrip('/')

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
        """One notification to the owner: Web Push to the phones of their app login; the DoniaLink App inbox
        adds the message (dl_app_alerts). Returns ({'delivered': …} once in an inbox, number of phones pushed).
        ``data`` and ``raise_errors`` are kept for the callers (nothing here can fail)."""
        self.ensure_one()
        box = self.sudo()
        pushed = box._app_push(title, body or text, route=route, card=card, tag=tag) if box.app_user_id else 0
        return {}, pushed

    def _app_devices(self):
        self.ensure_one()
        user = self.sudo().app_user_id
        if not user:
            return self.env['mail.push.device']
        return self.env['mail.push.device'].sudo().search([('partner_id', '=', user.partner_id.id)])

    @api.model
    def _dl_app_hash(self, route='home', card=None, box=None):
        """The cash box screen of the DoniaLink App for an owner app route: ``#cashbox/<box>/<page>``, the cards
        as ``#cashbox/<box>/card/<card>[/withdraw|expense|count|deposit]``."""
        box_id = _record_id(box) or (self.id if len(self) == 1 else 0)
        card_id = _record_id(card)
        parts = list(DL_APP_ROUTES.get(route or 'home', []))
        if parts and parts[0] == 'card':
            parts = ['card', str(card_id)] + parts[1:] if card_id else []
        elif not parts and card_id:
            parts = ['card', str(card_id)]
        return '#' + '/'.join([DL_APP_SCREEN] + ([str(box_id)] if box_id else []) + parts)

    def _app_url(self, route='home', card=None):
        """Where a notification of this box opens: the cash box screen (``route``, the ``card``) of the
        DoniaLink App, which replaced the owner app at /ecc/owner/app."""
        self.ensure_one()
        return '/dl/app' + self._dl_app_hash(route, card)

    @api.model
    def dl_app_cashbox_badge(self):
        """The number on the cash box tile of the DoniaLink App: sessions to collect and statements to answer."""
        count = 0
        for box in self._app_boxes(self.env.user):
            box = box.with_company(box.company_id)
            count += box.uncollected_session_count
            count += len(box.statement_ids.filtered(lambda s: s.state == 'sent'))
        return count

    def _app_push(self, title, body, route='home', card=None, tag=None):
        """Queue a notification to the phones where the owner turned notifications on. Never raises: a
        notification must not stop the action that sent it. Tapping it opens the app on ``route`` (and the
        ``card``) of this box. Returns the number of phones."""
        self.ensure_one()
        url = self._app_url(route, card)
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
    # Data shown by the app
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


class DonialinkAppScreen(models.Model):
    _inherit = 'donialink.app.screen'

    @api.model
    def _for_user(self, user=None):
        """The cash box tile of the DoniaLink App only for people linked to a cash box (Owner App Login)."""
        screens = super()._for_user(user)
        if DL_APP_SCREEN in screens.mapped('key') and not self.env['ecc.owner.box']._app_boxes(user or self.env.user):
            screens = screens.filtered(lambda s: s.key != DL_APP_SCREEN)
        return screens
