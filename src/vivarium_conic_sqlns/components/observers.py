import pathlib

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


class SampleHistoryObserver:

    configuration_defaults = {
        'metrics': {
            'sample_history': {
                'sample_proportion': 0.01,
                'path': '~/sample_history.hdf',
            },
        },
    }

    @property
    def name(self):
        return "sample_history_observer"

    def __init__(self):
        self.history_snapshots = []
        self.sample_index = pd.Index([])

    def setup(self, builder):
        config = builder.configuration['metrics']['sample_history']
        self.sample_proportion = config['sample_proportion']
        self.path = pathlib.Path(config['path']).resolve()
        if self.path.suffix != '.hdf':
            raise ValueError("metrics: sample_history: path must specify a path to an HDF file.")

        self.clock = builder.time.clock()
        self.randomness = builder.randomness.get_stream('sample_index')

        self.population_view = builder.population.get_view(['alive', 'age', 'sex', 'exit_time',
                                                            'sqlns_treatment_start', 'sqlns_treatment_end'])

        self.pipelines = {
            'iron_deficiency_exposure': builder.value.get_value('iron_deficiency.exposure'),
            'child_stunting_exposure': builder.value.get_value('child_stunting.exposure'),
            'child_wasting_exposure': builder.value.get_value('child_wasting.exposure'),
            'lower_resipratory_infections_incidence_rate': builder.value.get_value('lower_respiratory_infections.incidence_rate'),
            'lower_resipratory_infections_disability_weight': builder.value.get_value('lower_respiratory_infections.disability_weight'),
            'diarrheal_diseases_incidence_rate' : builder.value.get_value('diarrheal_diseases.incidence_rate'),
            'diarrheal_diseases_disability_weight': builder.value.get_value('diarrheal_diseases.disability_weight'),
            'measles_incidence_rate': builder.value.get_value('measles.incidence_rate'),
            'measles_disability_weight': builder.value.get_value('measles.disability_weight'),
            'iron_deficiency_disability_weight': builder.value.get_value('iron_deficiency.disability_weight'),
            'protein_energy_malnutrition_disability_weight': builder.value.get_value('protein_energy_malnutrition.disability_weight'),
            'disability_weight': builder.value.get_value('disability_weight')
        }

        builder.population.initializes_simulants(self.get_sample_index)
        builder.event.register_listener('collect_metrics', self.record)
        builder.event.register_listener('simulation_end', self.dump_history)

    def get_sample_index(self, pop_data):
        newly_sampled_idx = self.randomness.filter_for_probability(pop_data.index, self.sample_proportion)
        self.sample_index = self.sample_index.append(newly_sampled_idx)

    def record(self, event):
        pop = self.population_view.get(self.sample_index)
        pipeline_results = []
        for name, pipeline in self.pipelines.items():
            if name.endswith('_exposure'):
                skip_post_processor = True  # we want continuous exposures
            else:
                skip_post_processor = False

            # Using pop.index due to untracked individuals
            values = pipeline(pop.index, skip_post_processor=skip_post_processor)
            values = values.rename(name)
            pipeline_results.append(values)

            # some pipelines sources aren't really a 'baseline'
            if not name.endswith('disability_weight') and not name.endswith('_incidence_rate'):
                raw_values = pipeline.source(pop.index)
                raw_values = raw_values.rename(f'{name}_baseline')
                pipeline_results.append(raw_values)

        record = pd.concat(pipeline_results + [pop], axis=1)
        record['time'] = self.clock()
        record.index.rename("simulant", inplace=True)
        record.set_index('time', append=True, inplace=True)

        self.history_snapshots.append(record)

    def dump_history(self, event):
        sample_history = pd.concat(self.history_snapshots, axis=0)
        sample_history.to_hdf(self.path, key='sample_histories')


class SQLNSObserver:
    """Observer for total days treated with SQLNS."""

    @property
    def name(self):
        return 'sqlns_observer'

    def setup(self, builder):
        self.population_view = builder.population.get_view(['tracked', 'exit_time',
                                                            'sqlns_treatment_start', 'sqlns_treatment_end'])
        builder.value.register_value_modifier('metrics', self.metrics)

    def metrics(self, index, metrics):
        pop = self.population_view.get(index)
        treated = pop.loc[~pop['sqlns_treatment_start'].isnull()]

        treatment_end = treated['sqlns_treatment_end'].copy()
        died_before_treatment_end = treated['exit_time'] < treatment_end
        treatment_end.loc[died_before_treatment_end] = treated.loc[died_before_treatment_end, 'exit_time']

        treatment_days = (treated['sqlns_treatment_start'] - treatment_end) / pd.Timedelta(days=1)

        metrics['sqlns_treated_days'] = treatment_days.sum()
        return metrics
