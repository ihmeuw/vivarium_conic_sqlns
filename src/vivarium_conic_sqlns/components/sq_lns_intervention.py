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


class SQLNSEffect:

    configuration_defaults = {
        "sqlns": {
            "effect": {
                "mean": 0.0,
                "sd": 0.0,
                "individual_sd": 0.0,
                "permanent": False,
                "ramp": 28,  # Length of ramp up, ramp down time in days.
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

        builder.population.initializes_simulants(self.on_initialize_simulants)
        self.pop_view = builder.population.get_view(['sqlns_treatment_start', 'sqlns_treatment_end'])

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
        untreated, ramp_up, full_treatment, ramp_down, post_treatment = self.get_treatment_groups(index)

        effect_size.loc[untreated] = 0
        effect_size.loc[ramp_up] = self.ramp_efficacy(ramp_up)
        effect_size.loc[full_treatment] = self._effect_size.loc[full_treatment]
        if self.config.permanent:
            effect_size.loc[ramp_down] = self._effect_size[ramp_down]
            effect_size.loc[post_treatment] = self._effect_size[post_treatment]
        else:
            effect_size.loc[ramp_down] = self.ramp_efficacy(ramp_down, invert=True)
            effect_size.loc[post_treatment] = 0

        return exposure + effect_size

    def get_treatment_groups(self, index):
        ramp_time = pd.Timedelta(days=self.config.ramp)

        pop = self.pop_view.get(index)
        untreated = pop.loc[(pop['sqlns_treatment_start'].isnull())
                            | (pop['sqlns_treatment_start'] <= self.clock())].index
        ramp_up = pop.loc[(pop['sqlns_treatment_start'] < self.clock())
                          & (self.clock() < pop['sqlns_treatment_start'] + ramp_time)].index
        full_treatment = pop.loc[(pop['sqlns_treatment_start'] + ramp_time <= self.clock())
                                 & (self.clock() <= pop['sqlns_treatment_end'])].index
        ramp_down = pop.loc[(pop['sqlns_treatment_end'] < self.clock())
                            & (self.clock() < pop['sqlns_treatment_end'] + ramp_time)].index
        post_treatment = pop.loc[pop['sqlns_treatment_end'] + ramp_time <= self.clock()].index

        return untreated, ramp_up, full_treatment, ramp_down, post_treatment

    def ramp_efficacy(self, index, invert=False):
        """Logistic growth/decline of effect size.

        We're using a logistic function here to give a smooth treatment ramp.
        A logistic function has the form L/(1 - e**(-k * (t - t0))
        Where
        L  : function maximum
        t0 : center of the function
        k  : growth rate

        We want the function to be 0 for times below the treatment start,
        then to ramp up to the maximum over sum duration, stay there until
        the treatment stops, then ramp back down over the same duration.
        This means we effectively want to squeeze a logistic function into
        the discontinuities between a step function.  Making a function
        that smoothly transitions would be more math than I want to do right
        now.  Making a function that almost smoothly transitions is pretty
        easy and involves picking a growth rate that gets us very close
        to 0 and the maximum effect when we transition between constant
        effect sizes and the growth periods.

        I've parameterized in terms of the inverse of the  proportion of the
        maximum effect size, p, so that the jump between the different
        sections of the function is equal to (1 / p) * L.

        """
        if index.empty:
            return pd.Series()

        pop = self.pop_view.get(index)
        # 1/p is the proportion of the maximum effect.
        # Size of the discontinuity between constant and logistic functions.
        p = 10_000
        growth_rate = 2 / self.config.ramp * np.log(p)
        ramp_days = pd.Timedelta(days=self.config.ramp)

        if invert:
            ramp_position = ((pop['sqlns_treatment_end'] + ramp_days / 2) - self.clock()) / pd.Timedelta(days=1)
        else:
            ramp_position = (self.clock() - (pop['sqlns_treatment_start'] + ramp_days / 2)) / pd.Timedelta(days=1)

        scale = 1 / (1 + np.exp(-growth_rate * ramp_position))
        return scale * self._effect_size[index]
