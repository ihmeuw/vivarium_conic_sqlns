import numpy as np
import pandas as pd
from scipy import stats
from vivarium.framework.event import Event
from vivarium_public_health.utilities import TargetString


class SQLNSTreatmentAlgorithm:

    configuration_defaults = {
        "sqlns": {
            "start_date": {
                "year": 2020,
                "month": 1,
                "day": 1
            },
            "treatment_age": {
                "start": 0.5,
                "end": 1.0
            },
            "duration": 365.25,
            "program_coverage": 0.0
        }
    }

    @property
    def name(self):
        return "sqlns_treatment_algorithm"

    def setup(self, builder):
        config = builder.configuration['sqlns']
        self.start_date = pd.Timestamp(**config['start_date'].to_dict())
        self.duration = pd.Timedelta(days=config['duration'])
        self.treatment_age = config['treatment_age']
        self.coverage = config['program_coverage']

        self.clock = builder.time.clock()

        self.rand = builder.randomness.get_stream("sqlns_coverage")

        created_columns = ['sqlns_treatment_start', 'sqlns_treatment_end']
        required_columns = ['age']

        self.pop_view = builder.population.get_view(created_columns + required_columns)
        builder.population.initializes_simulants(self.on_initialize_simulants,
                                                 creates_columns=created_columns,
                                                 requires_columns=required_columns)

        builder.event.register_listener('time_step', self.on_time_step)

        builder.value.register_value_producer('sqlns.coverage', source=self.is_covered)

    def on_initialize_simulants(self, pop_data):
        if pop_data.user_data['sim_state'] == 'setup' and pop_data.creation_time >= self.start_date:
            raise NotImplementedError("SQ-LNS intervention must begin strictly after the intervention start date.")

        pop = pd.DataFrame({'sqlns_treatment_start': pd.NaT, 'sqlns_treatment_end': pd.NaT},
                           index=pop_data.index)
        self.pop_view.update(pop)

    def on_time_step(self, event):
        pop = self.pop_view.get(event.index, query="alive == 'alive'")
        treated_idx = self.get_treated_idx(pop, event)

        pop.loc[treated_idx, 'sqlns_treatment_start'] = event.time
        pop.loc[treated_idx, 'sqlns_treatment_end'] = event.time + self.duration
        self.pop_view.update(pop)

    def get_treated_idx(self, pop: pd.DataFrame, event: Event):
        pop_age_at_event = pop.age + (event.step_size / pd.Timedelta(days=365.25))
        if self.clock() < self.start_date <= event.time:
            # mass treatment when intervention starts
            eligible_idx = pop.loc[(self.treatment_age['start'] <= pop['age']) &
                                   (pop['age'] <= self.treatment_age['end'])].index
            treated_idx = self.rand.filter_for_probability(eligible_idx, self.coverage)
        elif self.start_date <= self.clock():
            # continuous enrollment for new 6-month-olds
            eligible_pop = pop.loc[(pop.age < self.treatment_age['start']) &
                                   (self.treatment_age['start'] <= pop_age_at_event)]
            treated_idx = self.rand.filter_for_probability(eligible_pop.index, self.coverage)
        else:
            # Intervention hasn't started.
            treated_idx = pd.Index([])

        return treated_idx

    def is_covered(self, index):
        pop = self.pop_view.get(index)
        return pop[(pop['sqlns_treatment_start'] <= self.clock()) & (self.clock() <= pop['sqlns_treatment_end'])].index


class SQLNSEffect:

    configuration_defaults = {
        "sqlns": {
            "effect": {
                "mean": 0.0,
                "sd": 0.0,
                "individual_sd": 0.0,
                "permanent": False,
            }
        }
    }

    def __init__(self, target):
        self.target = TargetString(target)
        self.configuration_defaults = {'sqlns': {f'effect_on_{self.target.name}': SQLNSEffect.configuration_defaults['sqlns']['effect']}}

    @property
    def name(self):
        return f'sqlns_effect_on_{self.target.name}'

    def setup(self, builder):
        self.config = builder.configuration.sqlns[f'effect_on_{self.target.name}']
        self.clock = builder.time.clock()

        self._effect_size = pd.Series()

        self.randomness = builder.randomness.get_stream(self.name)

        builder.value.register_value_modifier(f'{self.target.name}.{self.target.measure}', self.adjust_exposure)
        self.currently_covered = builder.value.get_value('sqlns.coverage')
        builder.population.initializes_simulants(self.on_initialize_simulants)
        self.pop_view = builder.population.get_view(['sqlns_treatment_start'])

    def on_initialize_simulants(self, pop_data):
        rs = np.random.RandomState(seed=self.randomness.get_seed())

        if self.config.sd > 0:
            individual_mean = rs.normal(self.config.mean, self.config.sd)
        else:
            individual_mean = self.config.mean

        if self.config.individual_sd > 0:
            draw = self.randomness.get_draw(pop_data.index, additional_key='effect_size')
            effect_size = stats.norm(individual_mean, self.config.individual_sd).ppf(draw)
            effect_size[effect_size < 0] = 0
        else:
            effect_size = individual_mean

        self._effect_size = self._effect_size.append(pd.Series(effect_size, index=pop_data.index))

    def adjust_exposure(self, index, exposure):
        effect_size = pd.Series(0, index=index)

        if self.config.permanent:
            pop = self.pop_view.get(index)
            effectively_treated = pop.loc[pop['sqlns_treatment_start'] <= self.clock()]
        else:
            effectively_treated = self.currently_covered(index)

        effect_size.loc[effectively_treated] = self._effect_size.loc[effectively_treated]
        return exposure + effect_size
