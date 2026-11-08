# -*- coding: utf-8 -*-
"""Reminders to the owner, on every channel of the box (Odoo app Web Push, DoniaLink app, Telegram):
- every day at the reminder hour, when nothing was recorded that day: record your cash expenses;
- once a week, on the count day at the same hour: count the cash you hold and confirm the balance.
"""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, modules, _
from odoo.exceptions import ValidationError

from .owner_box import WEEKDAYS

RECORDED_KINDS = ('expense', 'drawing')   # expense / took for me, on the cash box or on a card


class OwnerBox(models.Model):
    _inherit = 'ecc.owner.box'

    reminder_expense = fields.Boolean(
        'Daily Expense Reminder', default=True,
        help='At the reminder hour, when the owner recorded no expense and took nothing that day, he is reminded to '
             'record his cash expenses.')
    reminder_hour = fields.Integer('Reminder Hour', default=21, help="Hour of the day (0-23), owner's time zone.")
    reminder_count_weekday = fields.Selection(
        WEEKDAYS, string='Count Reminder Day', default='4',
        help='On this day, at the reminder hour, the owner is asked to count his cash. Empty: never.')
    reminder_expense_on = fields.Date('Expense Reminder Checked', readonly=True, copy=False)
    reminder_count_on = fields.Date('Count Reminder Sent', readonly=True, copy=False)

    @api.constrains('reminder_hour')
    def _check_reminder_hour(self):
        if any(not 0 <= box.reminder_hour <= 23 for box in self):
            raise ValidationError(_('The reminder hour must be between 0 and 23.'))

    def _owner_tz(self):
        self.ensure_one()
        name = self.sudo().app_user_id.tz or self.company_id.partner_id.tz or self.env.user.tz or 'UTC'
        try:
            return pytz.timezone(name)
        except pytz.UnknownTimeZoneError:
            return pytz.utc

    def _owner_now(self):
        return datetime.now(pytz.utc).astimezone(self._owner_tz())

    def _recorded_on(self, day):
        """Did the owner record an expense or "took for me" on ``day`` (his time zone), cash or card?"""
        self.ensure_one()
        tz = self._owner_tz()
        start = tz.localize(datetime.combine(day, time.min)).astimezone(pytz.utc).replace(tzinfo=None)
        domain = [('box_id', '=', self.id), ('state', '!=', 'cancelled'), ('kind', 'in', RECORDED_KINDS),
                  ('date', '>=', start), ('date', '<', start + timedelta(days=1))]
        return bool(self.env['ecc.owner.move'].sudo().search_count(domain, limit=1)
                    or self.env['ecc.owner.card.move'].sudo().search_count(domain, limit=1))

    def _expense_reminder_due(self, now=None):
        """For the app home banner: reminder on, the hour passed and nothing recorded today."""
        self.ensure_one()
        now = now or self._owner_now()
        return bool(self.reminder_expense and now.hour >= self.reminder_hour and not self._recorded_on(now.date()))

    def _send_expense_reminder(self, day):
        self.ensure_one()
        env = self.with_context(lang=self._app_lang()).env
        text = env._("You haven't recorded any cash expense today. Balance: %(balance)s. Spent cash? Record it now.",
                     balance=self.currency_id.format(self.balance))
        return self._owner_notify(
            'reminder_expense', text, env._('Record your cash expenses'), route='expense',
            tag='reminder-%s-%s' % (self.id, day.isoformat()),
            data={'balance': self.balance, 'date': day.isoformat()})

    def _send_count_reminder(self, day):
        self.ensure_one()
        env = self.with_context(lang=self._app_lang()).env
        text = env._('Count the cash you hold and confirm the balance (%(balance)s).',
                     balance=self.currency_id.format(self.balance))
        year, week, _weekday = day.isocalendar()
        return self._owner_notify(
            'reminder_count', text, env._('Count your cash'), route='count',
            tag='count-%s-%s-W%02d' % (self.id, year, week),
            data={'balance': self.balance, 'date': day.isoformat()})

    def _run_reminders(self, now=None):
        """Send what is due now for this box; each reminder at most once a day (the cron runs every hour)."""
        self.ensure_one()
        now = now or self._owner_now()
        if now.hour < self.reminder_hour:
            return
        today = now.date()
        if self.reminder_expense and self.reminder_expense_on != today:
            self.reminder_expense_on = today
            if not self._recorded_on(today):
                self._send_expense_reminder(today)
        if self.reminder_count_weekday == str(today.weekday()) and self.reminder_count_on != today:
            self.reminder_count_on = today
            self._send_count_reminder(today)

    @api.model
    def _cron_owner_reminders(self):
        boxes = self.sudo().search([
            '|', ('reminder_expense', '=', True), ('reminder_count_weekday', '!=', False),
            '|', '|', ('telegram_user_id', '!=', False), ('app_user_id', '!=', False),
            ('platform_enabled', '=', True)])
        for box in boxes:
            box.with_company(box.company_id)._run_reminders()
            if not modules.module.current_test:
                self.env.cr.commit()   # a box reminded is not reminded again if a later one fails

    def _api_card(self):
        card = super()._api_card()
        box = self.sudo()
        now = box._owner_now()
        card.update({
            'recorded_today': box._recorded_on(now.date()),
            'expense_reminder_due': box._expense_reminder_due(now),
        })
        return card
