"""The features of the real training cuts (U11, mark real_data; AC12, AC13): what requirements.md, section 4, measured on the training rows
holds with the project's own features, and the country groups of the model come out of those rows (plan, section 10, [Verificar en U11]).
Only lines dated before 2011-03-01 are netted, so no line of a validation or test window is used (D19)."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from churnrisk.config import SealedConfig
from churnrisk.cuts import label, label_end, population
from churnrisk.features import compute_features, country_groups, known_before
from churnrisk.netting import customer_days, net_cancellations, netting_inputs

pytestmark = pytest.mark.real_data

TRAINING = [date(2010, 6, 1), date(2010, 7, 1), date(2010, 8, 1), date(2010, 9, 1), date(2010, 10, 1), date(2010, 11, 1), date(2010, 12, 1)]


def test_the_real_training_features_hold_what_the_requirements_measured(real_canonical, cfg):
    result, frame, _report = real_canonical
    view = SealedConfig.of(cfg, cfg.source.accepted_sha256)
    purchases, cancellations = netting_inputs(frame[frame["invoice_date"] < pd.Timestamp(2011, 3, 1)].reset_index(drop=True))
    rows = []
    for cut in TRAINING:
        days, lines = known_before(purchases, cancellations, cut)
        members = population(days, cut, view.label.active_days)
        features = compute_features(days, lines, cut, members, view)
        end = label_end(cut, view.label.horizon_days)
        churned = label(customer_days(net_cancellations(purchases, cancellations, end).net_lines), cut, view.label.horizon_days, members)
        rows.append(features.assign(churned=churned, cut_date=cut).set_index("cut_date", append=True).swaplevel())
    train = pd.concat(rows)
    assert len(train) == 15_297 and train.index.get_level_values("customer_id").nunique() == 3_942
    one_day = train["freq_total"] == 1
    assert (round(float(one_day.mean()), 3), round(float(train.loc[one_day, "churned"].mean()), 3)) == (0.270, 0.670), "requirements.md, section 4"
    december = train.xs(date(2010, 12, 1), level="cut_date")
    single = december["freq_total"] == 1
    assert (int(single.sum()), round(float(december.loc[single, "churned"].mean()), 3)) == (684, 0.825)
    assert (train["freq_365"] == train["freq_total"]).all(), "the file starts on 2009-12-01, so in the training cuts the year is all the history"
    assert (train["rec_days"].between(1, view.label.active_days)).all() and (train["freq_90"] >= 1).all()
    # 12 countries with at least 10 customers in the training rows, and «Otros» (D57; research.md's first look had 8 and «Otros»)
    assert country_groups(train, view.features.country_min_customers) == (
        "Australia", "Belgium", "Channel Islands", "France", "Germany", "Italy", "Netherlands", "Portugal", "Spain", "Sweden", "Switzerland",
        "United Kingdom", "Otros")
