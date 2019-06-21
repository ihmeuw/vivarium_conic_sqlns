import pathlib

import pandas as pd

from vivarium_public_health.metrics import Disability


class DisabilityObserver(Disability):
    """Standard vph disability observer only includes DiseaseModel and
    RiskAttributableDisease models. We need to extend it to include our
    custom iron deficiency hemoglobin component."""
    def setup(self, builder):
        super().setup(builder)
        self.causes.append('iron_deficiency')
        self.disability_weight_pipelines['iron_deficiency'] = builder.value.get_value('iron_deficiency.disability_weight')


class SampleHistoryObserver:

    configuration_defaults = {
        'metrics': {
            'sample_history': {
                'sample_proportion': 0.01,
                'path': '~/sample_history.hdf'
            }
        }
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
            if name != 'disability_weight' and not name.endswith('_incidence_rate'):
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
