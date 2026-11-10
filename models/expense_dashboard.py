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
        data['owner'] = self._owner_review()
        return data

    @api.model
    def _owner_review(self):
        """Owner cash boxes to review: their expenses, differences, disputed statements, cash to collect."""
        company = self.env.company
        currency = company.currency_id
        boxes = self.env['ecc.owner.box'].search([('company_id', '=', company.id)])
        if not boxes:
            return False
        cash_to_review = self.env['ecc.owner.move'].search_count([
            ('box_id', 'in', boxes.ids), ('review_state', '=', 'to_review')])
        card_to_review = self.env['ecc.owner.card.move'].search_count([
            ('company_id', '=', company.id), ('review_state', '=', 'to_review')])
        differences = self.env['ecc.owner.difference'].search([
            ('box_id', 'in', boxes.ids), ('state', '=', 'pending')])
        disputed = self.env['ecc.owner.statement'].search_count([
            ('box_id', 'in', boxes.ids), ('state', '=', 'disputed')])
        waiting = self.env['ecc.owner.statement'].search_count([
            ('box_id', 'in', boxes.ids), ('state', '=', 'sent')])
        uncollected = sum(boxes.mapped('uncollected_amount'))
        return {
            'expenses_to_review': cash_to_review + card_to_review,
            'cash_to_review': cash_to_review,
            'card_to_review': card_to_review,
            'differences': len(differences),
            'differences_fmt': currency.format(sum(abs(d.amount) for d in differences)),
            'statements_disputed': disputed,
            'statements_waiting': waiting,
            'uncollected_sessions': sum(boxes.mapped('uncollected_session_count')),
            'uncollected_fmt': currency.format(uncollected),
            'boxes': [{
                'id': box.id,
                'name': box.name,
                'balance': box.balance,
                'balance_fmt': box.currency_id.format(box.balance),
                'uncollected_fmt': box.currency_id.format(box.uncollected_amount) if box.uncollected_amount else '',
                'to_review': box.receipt_to_review_count + box.difference_pending_count,
            } for box in boxes],
        }
