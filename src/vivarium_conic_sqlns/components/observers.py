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
                'sample_size': 100,
                'path': '/dev/null'
            }
        }
    }

    @property
    def name(self):
        return "sample_history_observer"

    def __init__(self):
        self.history_snapshots = []
        self.sample_index = None

    def setup(self, builder):
        config = builder.configuration['metrics']['sample_history']
        self.sample_size = config['sample_size']
        self.path = config['path']

        self.clock = builder.time.clock()
        self.randomness = builder.randomness.get_stream('sample_index')

        self.population_view = builder.population.get_view(['alive', 'age', 'sex', 'exit_time'])

        self.pipelines = {
            'iron_deficiency': builder.value.get_value('iron_deficiency.exposure'),
            'haz': builder.value.get_value('child_stunting.exposure'),
            'whz': builder.value.get_value('child_wasting.exposure'),
            'lri': builder.value.get_value('lower_respiratory_infections.incidence_rate'),
            'diarrhea' : builder.value.get_value('diarrheal_diseases.incidence_rate'),
            'measles': builder.value.get_value('measles.incidence_rate'),
            'pem': builder.value.get_value('protein_energy_malnutrition.incidence_rate'),
            'disability_weight': builder.value.get_value('disability_weight')
        }

        builder.population.initializes_simulants(self.get_sample_index)
        builder.event.register_listener('collect_metrics', self.record)
        builder.event.register_listener('simulation_end', self.dump_history)

    def get_sample_index(self, pop_data):
        pop_size = len(pop_data.index)
        if self.sample_size > pop_size:
            raise ValueError("Sample size cannot exceed initial population size.")

        draw = self.randomness.get_draw(pop_data.index)
        priority_index = [i for d, i in sorted(zip(draw, pop_data.index), key=lambda x:x[0])]
        self.sample_index = pd.Index(priority_index[:self.sample_size])

    def record(self, event):
        pop = self.population_view.get(self.sample_index)

        pipeline_results = []
        for name, pipeline in self.pipelines.items():
            if name == 'iron_deficiency':
                skip_post_processor = True
            else:
                skip_post_processor = False

            values = pipeline(self.sample_index, skip_post_processor=skip_post_processor)
            values = values.rename(name)
            pipeline_results.append(values)

            raw_values = pipeline.source(self.sample_index)
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
