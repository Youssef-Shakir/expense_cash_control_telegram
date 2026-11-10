# -*- coding: utf-8 -*-
"""Owner cash box actions shared by every channel: the Odoo owner app (/ecc/owner/app), the DoniaLink Platform
app and the Telegram bot (connector tools). The caller checks who may open the box; the service checks the
values, records through the box / card methods and answers with the same data everywhere.

The channel comes from the context: ``ecc_source`` ('app', 'platform', 'telegram') and ``ecc_actor`` (name of
the person when it is not the box owner's own login, e.g. a DoniaLink app user).
"""
import base64
import binascii
import re

from odoo import api, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_round

UID_RE = re.compile(r'^[A-Za-z0-9_-]{8,64}$')
MAX_PHOTOS = 5
MAX_PHOTO_BYTES = 8 * 1024 * 1024


class OwnerServiceError(UserError):
    """A refusal shown to the owner as is, with a code for the caller (refused, not_found, invalid_photo...)."""

    def __init__(self, message, code='refused'):
        super().__init__(message)
        self.code = code


class OwnerService(models.AbstractModel):
    _name = 'ecc.owner.service'
    _description = 'Owner Cash Box Actions'

    # ------------------------------------------------------------------
    # Channel
    # ------------------------------------------------------------------

    def _source(self):
        return self.env.context.get('ecc_source') or 'app'

    def _log(self, box, text):
        """Who did it, in the box chatter, when the channel acts for someone else than the box login."""
        actor = self.env.context.get('ecc_actor')
        if actor and text:
            box.sudo().message_post(body=_('%(actor)s via DoniaLink app: %(text)s', actor=actor, text=text))

    # ------------------------------------------------------------------
    # Values
    # ------------------------------------------------------------------

    @api.model
    def _amount(self, box, value, allow_none=False):
        if value in (None, '') and allow_none:
            return None
        try:
            amount = float(value)
        except (TypeError, ValueError):
            raise OwnerServiceError(_('Enter a valid amount.')) from None
        amount = float_round(amount, precision_rounding=box.currency_id.rounding)
        if amount <= 0:
            raise OwnerServiceError(_('The amount must be positive.'))
        return amount

    @api.model
    def _counted(self, currency, value):
        try:
            counted = float_round(float(value), precision_rounding=currency.rounding)
        except (TypeError, ValueError):
            raise OwnerServiceError(_('Enter a valid amount.')) from None
        if counted < 0:
            raise OwnerServiceError(_('The amount cannot be negative.'))
        return counted

    @api.model
    def _note(self, note):
        return (note or '').strip()[:500] or None

    @api.model
    def _request_uid(self, request_uid):
        if request_uid and UID_RE.match(str(request_uid)):
            return str(request_uid)
        return None

    @api.model
    def _photos(self, photos):
        """[{content_b64, filename, mimetype, ...}] → [{content, filename, mimetype, ...}] (images only)."""
        decoded = []
        for index, photo in enumerate((photos or [])[:MAX_PHOTOS]):
            try:
                content = base64.b64decode((photo or {}).get('content_b64') or '', validate=True)
            except (binascii.Error, ValueError, AttributeError):
                raise OwnerServiceError(_('A photo could not be read. Take it again.'), 'invalid_photo') from None
            if not content or len(content) > MAX_PHOTO_BYTES:
                raise OwnerServiceError(_('A photo is too large.'), 'invalid_photo')
            mimetype = photo.get('mimetype') or 'image/jpeg'
            if not mimetype.startswith('image/'):
                raise OwnerServiceError(_('Only photos can be attached.'), 'invalid_photo')
            extra = {k: photo[k] for k in ('message_id', 'file_unique_id') if photo.get(k)}
            decoded.append(dict(extra, content=content, mimetype=mimetype,
                                filename=(photo.get('filename') or 'receipt-%s.jpg' % (index + 1))[:200]))
        return decoded

    @api.model
    def _category(self, box, category_id):
        category = box._api_category(category_id)
        if not category:
            raise OwnerServiceError(_('Choose a category.'), 'not_found')
        return category

    @api.model
    def _card(self, box, card_id):
        card = box._app_card(card_id)
        if not card:
            raise AccessError(_('This card is not shared with you.'))
        return card.with_company(card.company_id).with_context(self.env.context)

    # ------------------------------------------------------------------
    # Answers and retries
    # ------------------------------------------------------------------

    @api.model
    def _done(self, box, move, text, **extra):
        self._log(box, text)
        return dict(extra, card=box._api_card(), text=text, move_id=move.id if move else False)

    @api.model
    def _card_done(self, box, card, move, text, **extra):
        self._log(box, text)
        return dict(extra, card=box._api_card(), bank_card=card._api_summary(), text=text,
                    move_id=move.id if move else False)

    def _saved_text(self, move, currency):
        return _('Already saved: %(name)s · %(amount)s', name=move.name, amount=currency.format(move.amount))

    @api.model
    def _replay(self, box, request_uid):
        """The same action sent again (no answer reached the phone): answer with what is saved."""
        if not request_uid:
            return None
        move = self.env['ecc.owner.move'].sudo().search(
            [('box_id', '=', box.id), ('app_request_uid', '=', request_uid)], limit=1)
        if not move:
            return None
        result = dict(card=box._api_card(), move_id=move.id, replayed=True,
                      text=self._saved_text(move, box.currency_id))
        if move.card_id:
            result['bank_card'] = move.card_id._api_summary()
        return result

    @api.model
    def _card_replay(self, box, card, request_uid):
        if not request_uid:
            return None
        move = self.env['ecc.owner.card.move'].sudo().search(
            [('card_id', '=', card.id), ('app_request_uid', '=', request_uid)], limit=1)
        if not move:
            return None
        return dict(card=box._api_card(), bank_card=card._api_summary(), move_id=move.id, replayed=True,
                    text=self._saved_text(move, card.currency_id))

    @api.model
    def _stamp(self, move, request_uid):
        if request_uid and move:
            move.sudo().app_request_uid = request_uid

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @api.model
    def statements(self, box, limit=12):
        return {'statements': box._api_statements(min(max(int(limit or 12), 1), 50)), 'card': box._api_card()}

    @api.model
    def cards(self, box):
        return {'cards': [card._api_summary() for card in box.sudo().card_ids.filtered('active')]}

    @api.model
    def card_home(self, box, card_id, limit=30):
        card = self._card(box, card_id)
        return {'bank_card': card._api_summary(),
                'moves': card._api_moves(min(max(int(limit or 30), 1), 100)), 'card': box._api_card()}

    # ------------------------------------------------------------------
    # Cash box
    # ------------------------------------------------------------------

    @api.model
    def collect(self, box, session_id, amount=None, request_uid=None):
        request_uid = self._request_uid(request_uid)
        replay = self._replay(box, request_uid)
        if replay:
            return replay
        session = self.env['pos.session'].sudo().browse(int(session_id or 0)).exists()
        if not session:
            raise OwnerServiceError(_('Session not found.'), 'not_found')
        move = box._collect_session(session, self._amount(box, amount, allow_none=True), source=self._source())
        self._stamp(move, request_uid)
        return self._done(box, move, _('Collected %(amount)s from %(session)s', amount=box.currency_id.format(
            move.amount), session=session.name), sessions=box._api_sessions(30))

    @api.model
    def expense(self, box, amount, category_id, note=None, photos=None, request_uid=None, **telegram):
        """``telegram``: chat_id, message_id, sender of the bot message."""
        request_uid = self._request_uid(request_uid)
        replay = self._replay(box, request_uid)
        if replay:
            return replay
        amount = self._amount(box, amount)
        category = self._category(box, category_id)
        move = box._record_expense(amount, category, note=self._note(note), photos=self._photos(photos),
                                   source=self._source())
        self._stamp(move, request_uid)
        return self._done(box, move, _('Expense %(amount)s (%(category)s) recorded · waiting for accountant '
                                       'review', amount=box.currency_id.format(amount), category=category.name),
                          receipt_id=None, reference=move.account_move_id.name or move.name)

    @api.model
    def took(self, box, amount, note=None, request_uid=None):
        request_uid = self._request_uid(request_uid)
        replay = self._replay(box, request_uid)
        if replay:
            return replay
        move = box._record_drawing(self._amount(box, amount), self._note(note), source=self._source())
        self._stamp(move, request_uid)
        return self._done(box, move, _('Took %s for you', box.currency_id.format(-move.amount)))

    @api.model
    def deposit(self, box, amount, target, note=None, request_uid=None, card_id=None):
        if target not in ('bank', 'till', 'card'):
            raise OwnerServiceError(_('Choose bank, till or card.'))
        request_uid = self._request_uid(request_uid)
        replay = self._replay(box, request_uid)
        if replay:
            return replay
        if target == 'card':
            card = self._card(box, card_id)
            move, _card_move = card._deposit(box, self._amount(box, amount), self._note(note), source=self._source())
            self._stamp(move, request_uid)
            return self._card_done(box, card, move, _('Deposited %(amount)s to %(card)s',
                                                      amount=box.currency_id.format(-move.amount), card=card.name))
        move = box._record_deposit(self._amount(box, amount), target, self._note(note), source=self._source())
        self._stamp(move, request_uid)
        return self._done(box, move, _('Deposited %s', box.currency_id.format(-move.amount)))

    @api.model
    def count(self, box, counted):
        counted = self._counted(box.currency_id, counted)
        expected = box.balance
        difference = box._record_count(counted)
        fmt = box.currency_id.format
        if difference:
            text = _('You counted %(counted)s, the books say %(expected)s (difference %(difference)s). '
                     'The accountant will check it.', counted=fmt(counted), expected=fmt(expected),
                     difference=fmt(difference.amount))
        else:
            text = _('%s — it matches the books.', fmt(counted))
        return self._done(box, None, text, difference=difference.amount if difference else 0.0, expected=expected)

    # ------------------------------------------------------------------
    # Notification settings of the box (owner side)
    # ------------------------------------------------------------------

    @api.model
    def notifications(self, box):
        box = box.sudo()
        return {'notifications': {
            'session_closed': box.notify_session_close,
            'reminder_expense': box.reminder_expense,
            'reminder_count_weekday': box.reminder_count_weekday or None,
            'reminder_hour': box.reminder_hour,
        }}

    @api.model
    def set_notifications(self, box, session_closed=None, reminder_expense=None, reminder_count_weekday=False,
                          reminder_hour=None):
        """Change what the owner is told; a value left out (None) is kept. reminder_count_weekday: '0' (Monday)
        to '6', or None/'' for never; leave it out (False) to keep it."""
        vals = {}
        if session_closed is not None:
            vals['notify_session_close'] = bool(session_closed)
        if reminder_expense is not None:
            vals['reminder_expense'] = bool(reminder_expense)
        if reminder_count_weekday is not False:
            day = str(reminder_count_weekday) if reminder_count_weekday not in (None, '') else False
            if day and day not in {'0', '1', '2', '3', '4', '5', '6'}:
                raise OwnerServiceError(_('Choose a day of the week.'))
            vals['reminder_count_weekday'] = day
        if reminder_hour is not None:
            try:
                hour = int(reminder_hour)
            except (TypeError, ValueError):
                hour = -1
            if not 0 <= hour <= 23:
                raise OwnerServiceError(_('The reminder hour must be between 0 and 23.'))
            vals['reminder_hour'] = hour
        if vals:
            box.sudo().write(vals)
            self._log(box, _('notification settings changed'))
        result = self.notifications(box)
        result['text'] = _('Notification settings saved.')
        return result

    @api.model
    def statement_answer(self, box, statement_id, correct, note=None):
        statement = self.env['ecc.owner.statement'].sudo().browse(int(statement_id or 0)).exists()
        if not statement or statement.box_id != box:
            raise OwnerServiceError(_('Statement not found.'), 'not_found')
        if statement.state not in ('draft', 'sent'):
            raise OwnerServiceError(_('This statement was already answered.'))
        statement._answer(bool(correct), self._note(note))
        text = _('Thank you, statement confirmed.') if correct else \
            _('Noted. The accountant will check the statement with you.')
        return self._done(box, None, text, statement_state=statement.state, statements=box._api_statements())

    # ------------------------------------------------------------------
    # Cards
    # ------------------------------------------------------------------

    @api.model
    def card_withdraw(self, box, card_id, amount, target='box', note=None, request_uid=None):
        card = self._card(box, card_id)
        if target not in ('box', 'took'):
            raise OwnerServiceError(_('Choose where the cash goes.'))
        request_uid = self._request_uid(request_uid)
        replay = self._card_replay(box, card, request_uid)
        if replay:
            return replay
        move = card._withdraw(box, self._amount(box, amount), target, self._note(note), source=self._source())
        self._stamp(move, request_uid)
        fmt = box.currency_id.format
        if target == 'took':
            text = _('Took %(amount)s for you from %(card)s', amount=fmt(-move.amount), card=card.name)
        else:
            text = _('%(amount)s from %(card)s added to your cash', amount=fmt(-move.amount), card=card.name)
        return self._card_done(box, card, move, text)

    @api.model
    def card_expense(self, box, card_id, amount, category_id, note=None, photos=None, request_uid=None):
        card = self._card(box, card_id)
        request_uid = self._request_uid(request_uid)
        replay = self._card_replay(box, card, request_uid)
        if replay:
            return replay
        amount = self._amount(box, amount)
        category = self._category(box, category_id)
        move = card._record_expense(box, amount, category, note=self._note(note),
                                    photos=self._photos(photos), source=self._source())
        self._stamp(move, request_uid)
        return self._card_done(box, card, move, _('Card expense %(amount)s (%(category)s) recorded · waiting for '
                                                  'accountant review', amount=box.currency_id.format(amount),
                                                  category=category.name),
                               receipt_id=None, reference=move.account_move_id.name or move.name)

    @api.model
    def card_count(self, box, card_id, counted):
        card = self._card(box, card_id)
        counted = self._counted(card.currency_id, counted)
        expected = card.balance
        difference = card._record_count(box, counted)
        fmt = card.currency_id.format
        if difference:
            text = _('The bank shows %(counted)s, the books say %(expected)s (difference %(difference)s). '
                     'The accountant will check it.', counted=fmt(counted), expected=fmt(expected),
                     difference=fmt(difference.amount))
        else:
            text = _('%s — it matches the books.', fmt(counted))
        return self._card_done(box, card, None, text, difference=difference.amount if difference else 0.0,
                               expected=expected)
