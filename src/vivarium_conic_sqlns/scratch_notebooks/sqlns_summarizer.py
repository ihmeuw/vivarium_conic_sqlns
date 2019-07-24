import numpy as np, pandas as pd
# import os
from collections import Counter
#from neonatal.tabulation import risk_mapper

# Used in .find_columns() method to categorize all columns in the data.
# Dictionary to find output columns in specific catories by matching column names with regular expressions
# using pd.DataFrame.filter()
def default_column_categories_to_search_regexes():
    return {
        # Data about the simulation input parameters
        'input_draw': 'input_draw',
        'random_seed': 'random_seed',
        'location': 'location', # any column containing the string 'location'
        'intervention': '\w+\.\w+', # columns look like 'intervention_name.paramater'. Parameters determine scenario.
        # Metadata about the simulation runs
        'run_time': 'run_time', # simulation run time
        # Data about the simulation results
        'diseases_at_end': '_prevalent_cases_at_sim_end$', # cause prevalence at end of simulation
        'disease_event_count': '_event_count$', # disease events throughout simulation - columns end in '_event_count'
        'population': 'population', # population statistics at end of simulation
        'person_time': '^person_time', # string starts with 'person_time'
        'mortality': '^death_due_to_', # string starts with 'death_due_to_'
        'total_daly': '^years_lived_with_disability$|^years_of_life_lost$', # sum of these 2 columns = DALYs for whole sim
        'yld': '^ylds_due_to_', # YLD columns start with 'ylds_due_to_'
        'yll': '^ylls_due_to_', # YLL columns start with 'ylls_due_to_'
        'categorical_risk': '_cat\d+_exposed', # columns for categorical risk exposures contain, e.g. '_cat16_exposed'
        'graded_sequela': 'mild|moderate|severe|unexposed', # anemia, for example
    }

# Used in .reindex_sub_dataframes() method to create a MultiIndex from original one-level index.
# Dictionary to extract useful information from column names with regular expressions
# using pd.Series.str.extract()
# Comments show example column names to extract cause/metric and demographic details from:
def default_column_categories_to_extraction_regexes():
    return {
        'person_time':
            # 'person_time_in_2020_among_female_in_age_group_late_neonatal'
            # 'person_time_in_2024_among_male_in_age_group_1_to_4'
#             '(?P<person_time_metric>^person_time)_in_(?P<year>\d{4})_among_(?P<sex>\w+)_in_age_group_(?P<age_group>\w+$)',
            '^(?P<measure>person_time)(_in_(?P<year>\d{4}))?(_among_(?P<sex>male|female))?(_in_age_group_(?P<age_group>\w+))?$',
        'mortality':
            # 'death_due_to_lower_respiratory_infections'
            # 'death_due_to_other_causes'
            '^(?P<measure>death)_due_to_(?P<cause>\w+?)(?:_in_(?P<year>\d{4}))?(?:_among_(?P<sex>male|female))?(?:_in_age_group_(?P<age_group>\w+))?$',
        'yld':
            # 'ylds_due_to_diarrheal_diseases_in_2020_among_male_in_age_group_early_neonatal'
            # 'ylds_due_to_hemolytic_disease_and_other_neonatal_jaundice_in_2025_among_female_in_age_group_1_to_4'
#             '(?P<yld_cause_name>^ylds_due_to_\w+)_in_(?P<year>\d{4})_among_(?P<sex>\w+)_in_age_group_(?P<age_group>\w+$)',
            '^(?P<measure>ylds)_due_to_(?P<cause>\w+?)(?:_in_(?P<year>\d{4}))?(?:_among_(?P<sex>male|female))?(?:_in_age_group_(?P<age_group>\w+))?$',
        'yll':
            # 'ylls_due_to_protein_energy_malnutrition_in_2020_among_male_in_age_group_early_neonatal'
            # 'ylls_due_to_hemolytic_disease_and_other_neonatal_jaundice_in_2025_among_female_in_age_group_post_neonatal'
            # 'ylls_due_to_other_causes_in_2025_among_female_in_age_group_1_to_4'
            # 'ylls_due_to_protein_energy_malnutrition_among_male_in_age_group_early_neonatal',
            # 'ylls_due_to_hemolytic_disease_and_other_neonatal_jaundice_in_2025',
            # 'ylls_due_to_other_causes_in_age_group_1_to_4',
            # 'ylls_due_to_protein_energy_malnutrition',
#             '(?P<yll_cause_name>^ylls_due_to_\w+)_in_(?P<year>\d{4})_among_(?P<sex>\w+)_in_age_group_(?P<age_group>\w+$)',
            '^(?P<measure>ylls)_due_to_(?P<cause>\w+?)(?:_in_(?P<year>\d{4}))?(?:_among_(?P<sex>male|female))?(?:_in_age_group_(?P<age_group>\w+))?$',
    #     'total_daly': '',
    #     'categorical_risk': '',
    }

# Functions to return the 0.025-th and 0.975-th quantiles of a pd.Series.

def quantile_025(x: pd.Series) -> float:
    return x.quantile(0.025)

def quantile_975(x: pd.Series) -> float:
    return x.quantile(0.975)

class SQLNSOutputSummarizer():
    """Class to provide functions to summarize output from neonatal model"""
    
    def __init__(self, model_output_df, column_categories_to_search_regexes=None):
        """Initialize this object with a pandas DataFrame of output"""
        self.data = model_output_df
        self.column_categories_to_search_regexes = column_categories_to_search_regexes
        # Initializes self.columns, self.found_columns, self.missing_columns, self.repeated_columns, self.empty_categories:
#         self.find_columns(column_categories_to_search_regexes)
#         # Sub-DataFrames corresponding to each column category
#         self.subdata = {column_category: self.data[column_names]
#                         for column_category, column_names in self.columns.items()}
        # Initializes self.subdata, self.columns, 
        # self.found_columns, self.missing_columns, self.repeated_columns, self.empty_categories:
        self.column_categories_to_extraction_regexes = None
        self.index_columns = None
        self.categorize_data_by_column()
        
    def categorize_data_by_column(self, column_categories_to_search_regexes=None):
        """Categorize the columns in the data to make sure we don't miss anything or overcount"""
        
        # If dictionary was passed, replace any existing dictionary
        if column_categories_to_search_regexes is not None:
            self.column_categories_to_search_regexes = column_categories_to_search_regexes
        # Otherwise, use the existing dictionary if we have one, or initialize to default
        elif self.column_categories_to_search_regexes is None:
            self.column_categories_to_search_regexes = default_column_categories_to_search_regexes()
            
        if self.index_columns is not None:
            all_data = pd.concat([self.data.index.to_frame(), self.data], axis='columns')
        else:
            all_data = self.data
        
        # Create dictionary mapping each column category to a sub-dataframe of columns in that category
        self.subdata = {category: all_data.filter(regex=cat_regex)
                        for category, cat_regex in self.column_categories_to_search_regexes.items()}
            
        # Create dictionary mapping each column category to a pd.Index of column names in that category
        # 2019-07-18: Eliminating this attribute in favor of accessing column names via subdata frames.
#         self.columns = {category: self.data.filter(regex=cat_regex).columns
#                         for category, cat_regex in self.column_categories_to_search_regexes.items()}
#         self.columns = {category: df.columns for category, df in self.subdata.items()}

        # Get a list (or pd.Series) of the found columns to check for missing or duplicate columns
        # found_columns = pd.concat(pd.Series(col_names) for col_names in columns.values())
        self.found_columns = [column for cat_data in self.subdata.values() for column in cat_data.columns]

        # Find any missing or duplicate columns
        self.missing_columns = set(self.data.columns) - set(self.found_columns)
        self.repeated_columns = {column_name: count for column_name, count in Counter(self.found_columns).items() if count > 1}

        # Also find any categories that didn't return a match
        self.empty_categories = [category for category, cat_data in self.subdata.items() if len(cat_data.columns) == 0]
        
    def print_column_report(self):
        """
        Print the total number of columns and the number of columns found in each category. Also print
        the missing and repeated columns if there were any, and any categories that didn't return a match.
        """
        
        col_cat_counts = self.column_category_counts()
        
        print(f"Number of data columns in output: {len(self.data.columns)}")
        print(f"Total number of columns captured in categories: {sum(col_cat_counts.values())}\n")
        
        print("Number of columns in each category:\n", col_cat_counts, "\n")
        
        print(f"Missing ({len(self.missing_columns)} data column(s) not captured in a category):\n",
              self.missing_columns)
        print(f"\nRepeated ({len(self.repeated_columns)} data column(s) appearing in more than one category):\n",
              self.repeated_columns)
        print(f"\nEmpty categories ({len(self.empty_categories)} categories with no matching data columns):\n",
              self.empty_categories)
    
    def column_category_counts(self):
        """Get a dictionary mapping column categories to the number of columns found in that category."""
        return {category: len(cat_data.columns) for category, cat_data in self.subdata.items()}
        
    def column_categories(self):
        """Get the list of column categories."""
#         return list(self.column_categories_to_search_regexes.keys()) # This should be equivalent
        return list(self.subdata.keys())
    
    def columns(self, column_category):
        """Get the column names in the specified category."""
        return self.subdata[column_category].columns
    
    def rename_intervention_columns(self, column_name_mapper=None):
        """
        Shorten the intervention column names by removing 'neonatal_intervention.' from the beginning.
        Maybe it would be good to be able to specify custom column names as well...
        (These columns become part of the MultiIndex in the sum_over_random_seeds() method below.)
        """
        if column_name_mapper is None:
#         # Replace all characters from start up through '.' with the empty string - or use more descriptive version below 
#         intervention_columns = self.columns['intervention'].str.replace(r'^.*\.', '')
            # Replace whole string with the short name that comes after the period:
            intervention_columns = self.columns('intervention').str.replace(r'.*\.(?P<short_name>.+)', r'\g<short_name>')
            column_name_mapper = {long_name: short_name for long_name, short_name
                                  in zip(self.columns('intervention'), intervention_columns)}
        else:
            intervention_columns = column_name_mapper.values()
        
        self.data = self.data.rename(columns=column_name_mapper)
        self.subdata['intervention'] = self.data[intervention_columns]
        self.column_categories_to_search_regexes['intervention'] = '|'.join(intervention_columns)
        
    def sum_over_random_seeds(self, index_columns=None):
        """
        Group the data by location, intervention parameters, and input draw, and sum values over random seeds.
        Maybe it would be good to be able to specify custom names for the new MultiIndex...
        """
#         self._rename_intervention_columns() # Replace the intervention column names with shorter versions
        if index_columns is not None:
            self.index_columns = index_columns
        elif self.index_columns is None:
            # location_intervention_draw
            self.index_columns = [*self.columns('location'), *self.columns('intervention'), *self.columns('input_draw')]
            
        self.data = self.data.drop(columns=self.columns('random_seed')) # We don't want to sum random seeds. Instead...
        self.data['random_seed_count'] = 1 # This will count random seeds when we do .groupby().sum()
        # Update the mapped random_seed column name with the new value (there may be a better way to do this...)
        # self.columns['random_seed'] = self.columns['random_seed'].str.replace('random_seed', 'random_seed_count')
        self.subdata['random_seed'] = self.data[['random_seed_count']] # Use a list to create a DataFrame rather than a Series
        
#         location_intervention_draw = [*self.columns('location'), *self.columns('intervention'), *self.columns('input_draw')]
        self.data = self.data.groupby(self.index_columns).sum()
        # Perhaps add some code to count random seeds per location_intervention_draw combination,
        # and count how many scenarios each draw appears in. Ok, random_seed_count is now included.
        # It could be useful to add separate functions to return DataFrames with the following columns:
        # a) location, random_seed_count, number_of_scenario_draw_combinations
        # b) location, draw_number, number_of_scenarios
        # These should be simple to implement by passing a Counter object into a new dataframe
#         self.subdata = {category: self.data.filter(regex=cat_regex)
#                         for category, cat_regex in self.column_categories_to_search_regexes.items()}
        self.categorize_data_by_column()
        
    def reindex_sub_dataframes(self, column_categories_to_extraction_regexes=None):
        """
        Create subdataframes for the specified categories with columns MultiIndexed by
        data extracted from original column names.
        """
        if column_categories_to_extraction_regexes is not None:
            self.column_categories_to_extraction_regexes = column_categories_to_extraction_regexes
        elif self.column_categories_to_extraction_regexes is None:
            self.column_categories_to_extraction_regexes = default_column_categories_to_extraction_regexes()
            
#         self.subdata = {}
        for category, extraction_regex in self.column_categories_to_extraction_regexes.items():
#             df = self.data[self.columns[category]]
#             column_decompositions = df.columns.str.extract(extraction_regex)
#             # Note: pd.MultiIndex.from_frame() requires pandas 0.24 or higher.
#             # If using version 0.23 or lower, instead use:
#             # pd.MultiIndex.from_tuples(column_decomposition.itertuples(index=False), names=column_decomposition.columns)
#             df.columns = pd.MultiIndex.from_frame(column_decompositions)
#             self.subdata[category] = df
            
            column_decompositions = self.subdata[category].columns.str.extract(extraction_regex)
            self.subdata[category].columns = pd.MultiIndex.from_frame(column_decompositions)


