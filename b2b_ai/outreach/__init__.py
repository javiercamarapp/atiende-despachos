# -*- coding: utf-8 -*-
"""Outreach: campañas automatizadas de outbound email para adquisición."""
from b2b_ai.outreach.sequences import (OutreachManager, SEQUENCE_TEMPLATES,
                                       SEQUENCE_SUBJECTS, FOLLOWUP_DAY_OFFSETS,
                                       render_template, render_subject,
                                       default_tracking_base)
from b2b_ai.outreach.analytics import (campaign_stats, lead_score,
                                       best_send_time, subject_line_ab_test)

__all__ = [
    "OutreachManager",
    "SEQUENCE_TEMPLATES", "SEQUENCE_SUBJECTS", "FOLLOWUP_DAY_OFFSETS",
    "render_template", "render_subject", "default_tracking_base",
    "campaign_stats", "lead_score", "best_send_time", "subject_line_ab_test",
]
