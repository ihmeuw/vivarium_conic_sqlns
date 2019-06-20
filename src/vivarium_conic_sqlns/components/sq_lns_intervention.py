import pandas as pd


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
        self.coverage = config['coverage']

        self.clock = builder.time.clock()

        created_columns = ['sqlns', 'treatment_start']
        required_columns = ['age']

        self.pop_view = builder.population.get_view(created_columns + required_columns)

        self.rand = builder.randomness.get_stream("sqlns_coverage")

        builder.population.initializes_simulants(self.on_initialize_simulants,
                                                 creates_columns=created_columns,
                                                 requires_columns=required_columns)
        builder.event.register_listener('time_step', self.on_time_step)

    def on_initialize_simulants(self, pop_data):
        pop = pd.DataFrame({'sqlns': False, 'treatment_start': pd.NaT},
                           index=pop_data.index)

        if self.start_date <= pop_data.creation_time:
            ages = self.pop_view.subview(['age']).get(pop_data.index)
            treated_idx = self.get_treated_idx(ages)
            pop.loc[treated_idx, 'sqlns'] = True
            pop.loc[treated_idx, 'treatment_start'] = pop_data.creation_time
            # FIXME: Uniformly distribute simulants between treat start and creation_time

        self.pop_view.update(pop)

    def on_time_step(self, event):

        pop = self.pop_view.get(event.index, query="alive == 'alive'")
        pop_age_at_event = pop.age + (event.step_size / pd.Timedelta(days=365.25))
        if self.clock() < self.start_date <= event.time:
            # mass treatment when intervention starts
            treated_idx = self.get_treated_idx(pop)
            pop.loc[treated_idx, 'sqlns'] = True
            pop.loc[treated_idx, 'treatment_start'] = event.time

        if self.start_date <= self.clock():
            # continuous enrollment for new 6-month-olds
            eligible_pop = pop.loc[(pop.age < self.treatment_age['start']) &
                                   (self.treatment_age['start'] <= pop_age_at_event)]
            treated_idx = self.rand.filter_for_probability(eligible_pop.index, self.coverage)
            pop.loc[treated_idx, 'sqlns'] = True
            pop.loc[treated_idx, 'treatment_start'] = event.time

        finished_treatment = (pop['sqlns']
                              & (pop['treatment_start'] - event.time >= self.duration))
        pop.loc[finished_treatment, 'sqlns'] = False

        self.pop_view.update(pop)

    def get_treated_idx(self, pop: pd.DataFrame):
        eligible_idx = pop.loc[(self.treatment_age['start'] <= pop['age']) &
                                (pop['age'] <= self.treatment_age['end'])].index

        return self.rand.filter_for_probability(eligible_idx, self.coverage)

