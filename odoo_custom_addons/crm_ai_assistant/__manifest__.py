{
    "name": "CRM AI Assistant",
    "version": "17.0.1.0.0",
    "category": "CRM",
    "summary": "AI enhancements for CRM leads",
    "description": "Adds AI summary, priority prediction, and email draft to CRM leads",
    "author": "Your Company",
    "license": "LGPL-3",
    "depends": ["base", "crm"],
    "data": [
        "views/crm_lead_ai_views.xml",
        "views/ai_chat_menu.xml"
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
