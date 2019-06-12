import numpy as np
import pandas as pd

from vivarium_public_health.utilities import EntityString
from vivarium_public_health.risks.data_transformations import get_distribution


class HemoglobinLevel:

    configuration_defaults = {
        "iron_deficiency": {
            "exposure": 'data',
            "rebinned_exposed": [],
            "category_thresholds": [],
        }
    }

    def __init__(self):
        self.name = "hemoglobin_level"
        self.risk = EntityString("risk_factor.iron_deficiency")

    def setup(self, builder):
        self.hemoglobin_distribution = get_distribution(builder, self.risk)
        builder.components.add_components([self.hemoglobin_distribution])

        self.anemia_thresholds = builder.lookup.build_table(get_anemia_thresholds(), key_columns=[],
                                                            parameter_columns=[('age',
                                                                                'age_group_start', 'age_group_end')],
                                                            value_columns=['anemia_thresholds', 'anemia_levels'])

        self.randomness = builder.randomness.get_stream('initial_hemoglobin_propensity')
        self._hemoglobin = pd.Series()

        self.hemoglobin_level = builder.value.register_value_producer(
            'hemoglobin_level',
            source=lambda index: self._hemoglobin[index],
            preferred_post_processor=self.get_hemoglobin_post_processor(),
        )

        builder.population.initializes_simulants(self.on_initialize_simulants)

    def on_initialize_simulants(self, pop_data):
        propensity = self.randomness.get_draw(pop_data.index)
        new_sims_hemoglobin = pd.Series(self.hemoglobin_distribution.ppf(propensity), index=pop_data.index)
        self._hemoglobin.append(new_sims_hemoglobin)

    def get_hemoglobin_post_processor(self):
        """Convert from raw hemoglobin level to anemia level."""

        def get_anemia_level(hemoglobin, anemia):
            return pd.cut(hemoglobin, anemia.anemia_thresholds[hemoglobin.name],
                          labels=anemia.anemia_levels[hemoglobin.name], right=False)

        def hemoglobin_to_anemia_post_processor(exposure, _):
            anemia = self.anemia_thresholds(exposure.index)
            return exposure.reset_index().apply(lambda hemo: get_anemia_level(hemo, anemia), axis=1)

        return hemoglobin_to_anemia_post_processor


def get_anemia_thresholds():
    """Thresholds from 'Severity definitions used to calculate GBD 2016 anemia
    envelope' table, pg. 763 in supplementary appendix 1 to GBD 2017 found here
    https://www.thelancet.com/cms/10.1016/S0140-6736(18)32279-7/attachment/b72819bc-83d9-441a-8edd-a7911a27597a/mmc1.pdf
    """

    return pd.DataFrame({'age_group_start': [0, 1 / 12],
                         'age_group_end': [1 / 12, 5],
                         'anemia_thresholds': [[-np.inf, 90, 130, 150, np.inf],
                                               [-np.inf, 70, 100, 110, np.inf]],
                         'anemia_levels': [['severe', 'moderate', 'mild', 'none']]*2})
