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
            preferred_post_processor=None,
        )

        self._disability_weight = builder.lookup.build_table(get_iron_deficiency_disability_weight(builder))
        self.disability_weight = builder.value.register_value_producer('iron_deficiency.disability_weight',
                                                                       source=self.compute_disability_weight)
        builder.value.register_value_modifier('disability_weight', modifier=self.disability_weight)

        builder.population.initializes_simulants(self.on_initialize_simulants)

    def on_initialize_simulants(self, pop_data):
        propensity = self.randomness.get_draw(pop_data.index)
        new_sims_hemoglobin = pd.Series(self.hemoglobin_distribution.ppf(propensity), index=pop_data.index)
        self._hemoglobin.append(new_sims_hemoglobin)

    def compute_disability_weight(self, index):
        anemia = self.anemia_thresholds(index)

        def get_anemia_level(hemoglobin):
            return pd.cut(hemoglobin, anemia.anemia_thresholds[hemoglobin.name],
                          labels=anemia.anemia_levels[hemoglobin.name], right=False)

        anemia_levels = self.hemoglobin_level(index).reset_index().apply(lambda hemo: get_anemia_level(hemo), axis=1)

        dw_info = self.disability_weight(index)
        dw = pd.Series(0, index=index)

        mild_index = anemia_levels == 'mild'
        dw.loc[mild_index] = dw_info.loc[mild_index]

        moderate_index = anemia_levels == 'moderate'
        dw.loc[moderate_index] = dw_info.loc[moderate_index]

        severe_index = anemia_levels == 'severe'
        dw.loc[severe_index] = dw_info.loc[severe_index]


def get_anemia_thresholds():
    """Thresholds from 'Severity definitions used to calculate GBD 2016 anemia
    envelope' table, pg. 763 in supplementary appendix 1 to GBD 2017 found here
    https://www.thelancet.com/cms/10.1016/S0140-6736(18)32279-7/attachment/b72819bc-83d9-441a-8edd-a7911a27597a/mmc1.pdf

    """
    return pd.DataFrame({'age_group_start': [0, 1, 5],
                         'age_group_end': [1 / 12, 5, 14],
                         'anemia_thresholds': [[-np.inf, 90, 130, 150, np.inf],
                                               [-np.inf, 70, 100, 110, np.inf],
                                               [-np.inf, 70, 100, 115, np.inf]],
                         'anemia_levels': [['severe', 'moderate', 'mild', 'none']]*3})


def get_iron_deficiency_disability_weight(builder):
    sequelae = builder.data.load(f'cause.dietary_iron_deficiency.sequelae')
    seq_dw = []
    for seq in sequelae:
        df = builder.data.load(f'sequela.{seq}.disability_weight')
        df = df.set_index(list(set(df.columns) - {'value'}))
        df = df.rename(columns={'value': seq.split('_')[0]})  # sequelae start with mild_, moderate_, severe_
        seq_dw.append(df)

    return pd.concat(seq_dw, axis=1).reset_index()