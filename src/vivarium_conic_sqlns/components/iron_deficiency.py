import pandas as pd

from vivarium_public_health.utilities import EntityString
from vivarium_public_health.risks import Risk
from vivarium_public_health.risks.data_transformations import get_distribution


class IronDeficiencyAnemia(Risk):

    def __init__(self, *_, **__):
        super().__init__("risk_factor.iron_deficiency")

    @property
    def name(self):
        return 'IronDeficiencyAnemia'

    def setup(self, builder):
        super().setup(builder)

        self.anemia_thresholds = builder.lookup.build_table(
            get_anemia_thresholds(),
            key_columns=[],
            parameter_columns=[('age', 'age_group_start', 'age_group_end')],
            value_columns=['severe_threshold', 'moderate_threshold', 'mild_threshold']
        )
        self._disability_weight_data = builder.lookup.build_table(get_iron_deficiency_disability_weight(builder))

        self.disability_weight = builder.value.register_value_producer('iron_deficiency.disability_weight',
                                                                       source=self.compute_disability_weight)
        builder.value.register_value_modifier('disability_weight', modifier=self.disability_weight)


        self.pop_view = builder.population.get_view(['alive', 'age'])

    def compute_disability_weight(self, index):
        disability_weight = pd.Series(0, index=index)

        disability_weight_data = self._disability_weight_data(index)
        mild, moderate, severe = self.split_for_anemia(index)

        disability_weight.loc[mild] = disability_weight_data.loc[mild, 'mild']
        disability_weight.loc[moderate] = disability_weight_data.loc[moderate, 'moderate']
        disability_weight.loc[severe] = disability_weight_data.loc[severe, 'severe']

        return disability_weight * (self.pop_view.get(index).alive == 'alive')

    def split_for_anemia(self, index):
        anemia = self.anemia_thresholds(index)
        hemoglobin = self.exposure(index)

        mild = (anemia.moderate_threshold <= hemoglobin) & (hemoglobin < anemia.mild_threshold)
        moderate = (anemia.severe_threshold <= hemoglobin) & (hemoglobin < anemia.moderate_threshold)
        severe = hemoglobin < anemia.severe_threshold

        return mild, moderate, severe


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
