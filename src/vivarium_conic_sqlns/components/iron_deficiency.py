import numpy as np
import pandas as pd

from vivarium_public_health.utilities import EntityString
from vivarium_public_health.risks.data_transformations import get_distribution


class Hemoglobin:

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

        self.pop_view = builder.population.get_view(['alive'])

        self.anemia_thresholds = builder.lookup.build_table(get_anemia_thresholds(), key_columns=[],
                                                            parameter_columns=[('age',
                                                                                'age_group_start',
                                                                                'age_group_end')],
                                                            value_columns=['severe_threshold', 'moderate_threshold',
                                                                           'mild_threshold'])

        self.randomness = builder.randomness.get_stream('initial_hemoglobin_propensity')
        self._hemoglobin = pd.Series()

        self.hemoglobin = builder.value.register_value_producer('hemoglobin',
                                                                source=lambda index: self._hemoglobin[index])

        self._disability_weight = builder.lookup.build_table(get_iron_deficiency_disability_weight(builder))
        self.disability_weight = builder.value.register_value_producer('iron_deficiency.disability_weight',
                                                                      source=self.compute_disability_weight)
        builder.value.register_value_modifier('disability_weight', modifier=self.disability_weight)

        builder.population.initializes_simulants(self.on_initialize_simulants)

    def on_initialize_simulants(self, pop_data):
        propensity = self.randomness.get_draw(pop_data.index)
        new_sims_hemoglobin = pd.Series(self.hemoglobin_distribution.ppf(propensity), index=pop_data.index)
        self._hemoglobin = self._hemoglobin.append(new_sims_hemoglobin)
        self.anemia_thresholds(pop_data.index)

    def compute_disability_weight(self, index):
        anemia = self.anemia_thresholds(index)
        hemoglobin = self.hemoglobin(index)
        severe_index = hemoglobin < anemia.severe_threshold
        moderate_index = (hemoglobin >= anemia.severe_threshold) & (hemoglobin < anemia.moderate_threshold)
        mild_index = (hemoglobin >= anemia.moderate_threshold) & (hemoglobin < anemia.mild_threshold)

        dw_info = self._disability_weight(index)
        dw = pd.Series(0, index=index)
        dw.loc[mild_index] = dw_info.loc[mild_index, 'mild']
        dw.loc[moderate_index] = dw_info.loc[moderate_index, 'moderate']
        dw.loc[severe_index] = dw_info.loc[severe_index, 'severe']

        return dw * (self.pop_view.get(index).alive == 'alive')


def get_anemia_thresholds():
    """Thresholds from 'Severity definitions used to calculate GBD 2016 anemia
    envelope' table, pg. 763 in supplementary appendix 1 to GBD 2017 found here
    https://www.thelancet.com/cms/10.1016/S0140-6736(18)32279-7/attachment/b72819bc-83d9-441a-8edd-a7911a27597a/mmc1.pdf

    Thresholds and age groups are inclusive on the left only: e.g., for
    ages < 1 month, severe anemia is hemoglobin in [0, 90).

    NOTE: thresholds for individuals 15 years and older vary by sex and,
    for women, pregnancy status. Since this is for a model of children,
    these numbers have been excluded for now.
    """
    return pd.DataFrame({'age_group_start': [0, 1 / 12, 5],
                         'age_group_end': [1 / 12, 5, 15],
                         'severe_threshold': [90, 70, 70],
                         'moderate_threshold': [130, 100, 100],
                         'mild_threshold': [150, 110, 115]})


def get_iron_deficiency_disability_weight(builder):
    sequelae = builder.data.load(f'cause.dietary_iron_deficiency.sequelae')
    seq_dw = []
    for seq in sequelae:
        df = builder.data.load(f'sequela.{seq}.disability_weight')
        df = df.set_index(list(set(df.columns) - {'value'}))
        df = df.rename(columns={'value': seq.split('_')[0]})  # sequelae start with mild_, moderate_, severe_
        seq_dw.append(df)

    return pd.concat(seq_dw, axis=1).reset_index()
