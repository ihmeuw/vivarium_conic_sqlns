from collections import Counter

import pandas as pd

from vivarium_public_health.risks import Risk
from vivarium_public_health.metrics.utilities import get_age_sex_filter_and_iterables, get_age_bins, get_output_template
from vivarium_public_health.utilities import EntityString


class VVIronDeficiencyAnemia(Risk):

    def __init__(self, *_, **__):
        super().__init__("risk_factor.iron_deficiency")
        self.configuration_defaults.update({
            'metrics': {
                'anemia_observer': {
                    'sample_date': {
                        'month': 7,
                        'day': 1,
                    },
                    'by_age': False,
                    'by_sex': False,
                }
            }
        })

    @property
    def name(self):
        return 'VVIronDeficiencyAnemia'

    def setup(self, builder):
        super().setup(builder)

        self.age_bins = get_age_bins(builder)
        self.anemia_counts = Counter()

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

        self.pop_view = builder.population.get_view(['alive', 'age', 'sex'])

        self.data = {}
        self.observer_config = builder.configuration['metrics']['anemia_observer']
        self.clock = builder.time.clock()
        builder.value.register_value_modifier('metrics', self.metrics)
        builder.event.register_listener('collect_metrics', self.on_collect_metrics)

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

    def on_collect_metrics(self, event):
        """Records counts of risk exposed by category."""
        pop = self.pop_view.get(event.index, query='alive == "alive"')

        if self.should_sample(event.time):
            age_sex_filter, (ages, sexes) = get_age_sex_filter_and_iterables(self.observer_config, self.age_bins)
            group_counts = {}

            for group, age_group in ages:
                start, end = age_group.age_group_start, age_group.age_group_end
                for sex in sexes:
                    filter_kwargs = {'age_group_start': start, 'age_group_end': end, 'sex': sex, 'age_group': group}
                    group_filter = age_sex_filter.format(**filter_kwargs)
                    in_group = pop.query(group_filter) if group_filter and not pop.empty else pop

                    anemia = self.split_for_anemia(in_group.index)

                    exposed_count = 0
                    for level, idx in zip(['mild', 'moderate', 'severe'], anemia):
                        base_key = get_output_template(**self.observer_config).substitute(
                            measure=f'{level}_anemia_counts', year=self.clock().year)
                        group_key = base_key.substitute(**filter_kwargs)

                        level_count = len(in_group[idx])
                        group_counts[group_key] = level_count
                        exposed_count += level_count

                    base_key = get_output_template(**self.observer_config).substitute(
                        measure='unexposed_anemia_counts', year=self.clock().year)
                    group_key = base_key.substitute(**filter_kwargs)
                    group_counts[group_key] = len(in_group) - exposed_count

            self.anemia_counts.update(group_counts)

    def should_sample(self, event_time: pd.Timestamp) -> bool:
        """Returns true if we should sample on this time step."""
        sample_date = pd.Timestamp(event_time.year,
                                   self.observer_config.sample_date.month,
                                   self.observer_config.sample_date.day)
        return self.clock() <= sample_date < event_time

    def metrics(self, index, metrics):
        metrics.update(self.anemia_counts)
        return metrics

    def __repr__(self):
        return f"VVIronDeficiencyAnemia"


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


class VVRiskObserver:
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
            f'{self.risk.name}_observer': VVRiskObserver.configuration_defaults['metrics']['risk_observer']
        }}

    @property
    def name(self):
        return f'vv_categorical_risk_observer.{self.risk}'

    def setup(self, builder):
        self.data = {}
        self.config = builder.configuration[f'metrics'][f'{self.risk.name}_observer']
        self.clock = builder.time.clock()
        self.categories = self.config.categories
        self.age_bins = get_age_bins(builder)

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
            for group, age_group in self.age_bins.iterrows():
                start, end = age_group.age_group_start, age_group.age_group_end
                in_group = pop[(pop.age >= start) & (pop.age < end)]
                sample.loc[group] = exposure.loc[in_group.index].value_counts()

            self.data[self.clock().year] = sample

    def should_sample(self, event_time: pd.Timestamp) -> bool:
        """Returns true if we should sample on this time step."""
        sample_date = pd.Timestamp(event_time.year, self.config.sample_date.month, self.config.sample_date.day)
        return self.clock() <= sample_date < event_time

    def generate_sampling_frame(self) -> pd.DataFrame:
        """Generates an empty sampling data frame."""
        sample = pd.DataFrame({f'{cat}': 0 for cat in self.categories}, index=self.age_bins.index)
        return sample

    def metrics(self, index, metrics):
        for age_id, age_group in self.age_bins.iterrows():
            age_group_name = age_group.age_group_name.replace(" ", "_").lower()
            for year, sample in self.data.items():
                for category in sample.columns:
                    label = f'{self.risk.name}_{category}_exposed_in_{year}_among_{age_group_name}'
                    metrics[label] = sample.loc[age_id, category]
        return metrics

    def __repr__(self):
        return f"VVCategoricalRiskObserver({self.risk})"