import pytest

from website_agent.database import Audit
from website_agent.pipeline import Pipeline


def high_score_audit(session, prospect):
    session.add(Audit(
        prospect_id=prospect.id, score=100,
        evidence={"snippets": ["Sample Salon", "Haircuts"]}, research={},
    ))
    session.commit()


def test_all_salons_mode_qualifies_real_business_even_with_strong_site(
    session, settings, config, prospect, fakes
):
    config.weak_websites_only = False
    high_score_audit(session, prospect)
    pipe = Pipeline(session, settings, config, ai=fakes.ai)
    pipe.start("daily", "all-salons-strong-site")
    pipe.audit(prospect)
    assert prospect.status == "qualified"
    assert pipe.run.summary["qualified"] == 1
    assert "strong_website_disqualified" not in pipe.run.summary


@pytest.mark.parametrize("stopped", [None, "unsubscribed", "rejected", "delivery_failure"])
def test_broadening_target_revisits_only_quality_exclusions(
    session, settings, config, prospect, fakes, stopped
):
    high_score_audit(session, prospect)
    pipe = Pipeline(session, settings, config, ai=fakes.ai)
    pipe.start("daily", "quality-filter-history")
    pipe.audit(prospect)
    assert prospect.status == "disqualified"
    if stopped:
        prospect.status = stopped
        session.commit()
    config.weak_websites_only = False
    from unittest.mock import Mock

    pipe.discover = Mock(return_value=False)
    pipe.generate = Mock(return_value=None)
    pipe.daily()
    if stopped:
        assert prospect.status == stopped
        pipe.generate.assert_not_called()
    else:
        assert prospect.status == "qualified"
        pipe.generate.assert_called_once_with(prospect)
        assert pipe.run.summary["quality_exclusion_reopened"] == 1


def test_unrelated_disqualification_is_not_reopened(session, settings, config, prospect, fakes):
    from unittest.mock import Mock

    config.weak_websites_only = False
    high_score_audit(session, prospect)
    prospect.status = "disqualified"
    session.commit()
    pipe = Pipeline(session, settings, config, ai=fakes.ai)
    pipe.start("daily", "not-quality-exclusion")
    pipe.discover = Mock(return_value=False)
    pipe.audit = Mock()
    pipe.daily()
    assert prospect.status == "disqualified"
    pipe.audit.assert_not_called()
