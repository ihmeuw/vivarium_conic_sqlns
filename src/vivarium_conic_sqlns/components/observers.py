import pandas as pd
from vivarium_public_health.utilities import EntityString
from vivarium_public_health.metrics import Disability


class DisabilityObserver(Disability):
    """Standard vph disability observer only includes DiseaseModel and
    RiskAttributableDisease models. We need to extend it to include our
    custom iron deficiency hemoglobin component."""
    def setup(self, builder):
        super().setup(builder)

        self.causes.append('iron_deficiency')
        self.disability_weight_pipelines['iron_deficiency'] = builder.value.get_value('iron_deficiency.disability_weight')




class RiskObserver:
    """ An observer for a categorical risk factor.

    This component observes the number of simulants in each age
    group who are alive and in each category of risk at the specified sample date each year
    (the sample date defaults to July, 1, and can be set in the configuration).

    Here is an example configuration to change the sample date to Dec. 31:

    .. code-block:: yaml

        {risk_name}_observer:
            sample_date:
                month: 12
                day: 31
    """
    configuration_defaults = {
        'metrics': {
            'risk_observer': {
                'categories': ['cat1', 'cat2', 'cat3', 'cat4'],
                'sample_date': {
                    'month': 7,
                    'day': 1
                }
            }
        }
    }

    def __init__(self, risk: str):
        """
        Parameters
        ----------
        risk :
        the type and name of a risk, specified as "type.name". Type is singular.

        """
        self.risk = EntityString(risk)
        self.configuration_defaults = {'metrics': {
            f'{self.risk.name}_observer': RiskObserver.configuration_defaults['metrics']['risk_observer']
        }}

    @property
    def name(self):
        return f'categorical_risk_observer.{self.risk}'

    def setup(self, builder):
        self.data = {}
        self.config = builder.configuration[f'metrics'][f'{self.risk.name}_observer']
        self.clock = builder.time.clock()
        self.categories = self.config.categories

        self.population_view = builder.population.get_view(['alive', 'age'], query='alive == "alive"')

        self.exposure = builder.value.get_value(f'{self.risk.name}.exposure')
        builder.value.register_value_modifier('metrics', self.metrics)

        builder.event.register_listener('collect_metrics', self.on_collect_metrics)

    def on_collect_metrics(self, event):
        """Records counts of risk exposed by category."""
        pop = self.population_view.get(event.index)

        if self.should_sample(event.time):
            sample = self.generate_sampling_frame()
            exposure = self.exposure(pop.index)
            sample.loc['0_to_5'] = exposure.value_counts()

            self.data[self.clock().year] = sample

    def should_sample(self, event_time: pd.Timestamp) -> bool:
        """Returns true if we should sample on this time step."""
        sample_date = pd.Timestamp(event_time.year, self.config.sample_date.month, self.config.sample_date.day)
        return self.clock() <= sample_date < event_time

    def generate_sampling_frame(self) -> pd.DataFrame:
        """Generates an empty sampling data frame."""
        sample = pd.DataFrame({f'{cat}': 0 for cat in self.categories}, index=['0_to_5'])
        return sample

    def metrics(self, index, metrics):
        for year, sample in self.data.items():
            for category in sample.columns:
                label = f'{self.risk.name}_{category}_exposed_in_{year}_among_0_to_5'
                metrics[label] = sample.loc['0_to_5', category]
        return metrics

    def __repr__(self):
        return f"CategoricalRiskObserver({self.risk})"

