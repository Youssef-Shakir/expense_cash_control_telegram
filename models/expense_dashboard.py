# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ExpenseCashDashboard(models.AbstractModel):
    _inherit = 'expense.cash.dashboard'

    @api.model
    def get_dashboard_data(self):
        data = super().get_dashboard_data()
        Receipt = self.env['ecc.receipt']
        domain = [('company_id', '=', self.env.company.id), ('state', '=', 'to_review')]
        count = Receipt.search_count(domain)
        oldest = Receipt.search(domain, order='sent_at asc', limit=1)
        data['receipts_to_review'] = count
        data['receipts_oldest_days'] = (fields.Datetime.now() - oldest.sent_at).days if oldest else 0
        data['receipts_waiting_answer'] = Receipt.search_count(domain + [('question_state', '=', 'waiting')])
        return data
