import pandas as pd

from vivarium.interpolation import Order0Interp

from vivarium_public_health.utilities import EntityString
from vivarium_public_health.risks.data_transformations import get_distribution


class HemoglobinLevel:

    configuration_defaults = {
        "risk": {
            "exposure": 'data',
            "rebinned_exposed": [],
            "category_thresholds": [],
        }
    }

    def __init__(self):
        self.name = "hemoglobin_level"
        self.risk = EntityString("risk_factor.iron_deficiency")
        self.configuration_defaults = {f'{self.risk.name}': HemoglobinLevel.configuration_defaults['risk']}

    def setup(self, builder):
        self.exposure_distribution = get_distribution(builder, self.risk)
        builder.components.add_components([self.exposure_distribution])

        self.anemia_thresholds = Order0Interp(get_anemia_thresholds(),
                                              parameter_columns=[('age', 'age_group_start', 'age_group_end'),
                                                                 ('hemoglobin', 'hemoglobin_start', 'hemoglobin_end')],
                                              value_columns=['anemia_severity'],
                                              extrapolate=builder.configuration.interpolation.extrapolate)
        self.pop_view = builder.population.get_view(['age'])

        self.randomness = builder.randomness.get_stream(f'initial_{self.risk.name}_propensity')
        self.propensity = pd.Series()

        self.exposure = builder.value.register_value_producer(
            f'{self.risk.name}.exposure',
            source=self.get_current_exposure,
            preferred_post_processor=self.get_exposure_post_processor()
        )

        builder.population.initializes_simulants(self.on_initialize_simulants)

    def on_initialize_simulants(self, pop_data):
        self.propensity = self.propensity.append(self.randomness.get_draw(pop_data.index))

    def get_current_exposure(self, index):
        propensity = self.propensity(index)
        return pd.Series(self.exposure_distribution.ppf(propensity), index=index)

    def get_exposure_post_processor(self):

        def post_processor(exposure, _):
            sims = self.pop_view.get(exposure.index)
            sims['hemoglobin'] = exposure
            return self.anemia_thresholds(sims)

        return post_processor


def get_anemia_thresholds():
    """Thresholds from 'Severity definitions used to calculate GBD 2016 anemia
    envelope' table, pg. 763 in supplementary appendix 1 to GBD 2017 found here
    https://www.thelancet.com/cms/10.1016/S0140-6736(18)32279-7/attachment/b72819bc-83d9-441a-8edd-a7911a27597a/mmc1.pdf
    """

    return pd.DataFrame({'age_group_start': [0] * 4 + [1] * 4,
                         'age_group_end': [1 / 12] * 4 + [5] * 4,
                         'hemoglobin_start': [0, 90, 130, 150, 0, 70, 100, 110],
                         'hemoglobin_end': [90, 130, 150, 500, 70, 100, 110, 500],
                         'anemia_severity': ['severe', 'moderate', 'mild', 'none'] * 2})
