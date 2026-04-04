from odoo import models, fields


class CrmLead(models.Model):
    _inherit = "crm.lead"

    ai_summary = fields.Text(string="AI Summary")
    ai_priority_prediction = fields.Selection(
        [("high", "High"), ("medium", "Medium"), ("low", "Low")],
        string="AI Predicted Priority",
    )
    ai_email_draft = fields.Html(string="AI Email Draft")
