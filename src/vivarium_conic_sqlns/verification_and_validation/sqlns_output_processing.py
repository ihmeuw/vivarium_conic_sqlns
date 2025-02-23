"""
Module for processing output of SQLNS model.
Code was copied from Nathaniel's notebook `2019_07_25_validation_with_treated_days.ipynb`
on 2019-07-30.

The following code ran successfully in the notebook `2019_07_30_verify_yld_bug_fix.ipynb`:

import vivarium_conic_sqlns.verification_and_validation.sqlns_output_processing as sop
result_dir = '/share/costeffectiveness/results/sqlns/presentation/nigeria/2019_07_30_00_01_45'
output = sop.load_output(result_dir, 'output.hdf')
df = sop.get_transformed_data(output)
averted_df = sop.get_averted_results(df)
aggregated_df = sop.get_final_table(averted_df)
"""

import pandas as pd

# cause_names = ['lower_respiratory_infections', 'measles', 'diarrheal_diseases', 
#                'protein_energy_malnutrition', 'iron_deficiency', 'other_causes']

# risk_names = ['anemia', 'child_stunting', 'child_wasting']

# template_cols = ['coverage', 'duration', 'child_stunting_permanent', 
#                  'child_wasting_permanent', 'iron_deficiency_permanent', 
#                  'iron_deficiency_mean', 'cause', 'measure', 'input_draw']

# join_columns = [c for c in template_cols if c not in ['cause', 'measure']]

# # Same as join_cols
# index_cols = ['coverage', 'duration', 'child_stunting_permanent', 
#                  'child_wasting_permanent', 'iron_deficiency_permanent', 
#                  'iron_deficiency_mean', 'input_draw']

# intervention_colname_mapper = {'sqlns.effect_on_child_stunting.permanent': 'child_stunting_permanent',
#                       'sqlns.effect_on_child_wasting.permanent': 'child_wasting_permanent',
#                       'sqlns.effect_on_iron_deficiency.permanent': 'iron_deficiency_permanent',
#                       'sqlns.effect_on_iron_deficiency.mean': 'iron_deficiency_mean',
#                       'sqlns.program_coverage': 'coverage',
#                       'sqlns.duration': 'duration'}

def load_output(path, filename):
    """Loads output file."""
    r = pd.read_hdf(f'{path}/{filename}')
    return r

def load_by_location_and_rundate(base_directory: str, locations_run_dates: dict) -> pd.DataFrame:
    """Load output.hdf files from folders namedd with the convention 'base_directory/location/rundate/output.hdf'"""
    
    # Use dictionary to map countries to the correct path for the Vivarium output to process
    # E.g. /share/costeffectiveness/results/sqlns/bangladesh/2019_06_21_00_09_53
    locactions_paths = {location: f'{base_directory}/{location.lower()}/{run_date}/output.hdf'
                       for location, run_date in locations_run_dates.items()}

    # Read in data from different countries
    locations_outputs = {location: pd.read_hdf(path) for location, path in locactions_paths.items()}

    for location, output in locations_outputs.items():
        output['location'] = location
    
    return pd.concat(locations_outputs.values(), copy=False, sort=False)
    
def print_location_output_shapes(locations, all_output):
    """Print the shapes of outputs for each location to check whether all the same size or if some data is missing"""
    for location in locations:
        print(location, all_output.loc[all_output.location==location].shape)

# note that we have applied coefficient of variation as constant with different sqlns effect on iron deficiency
def clean_and_aggregate(r, colname_mapper, index_cols, coverage_col):
    """
    Does the following "cleaning" steps, then sums over random seeds.
    Cleaning steps:
        1. Rename intervention columns with shorter names.
        2. Multiply coverage by 100 to convert to percent.
    """
#     r = pd.read_hdf(path + 'nigeria/2019_07_18_13_20_17/output.hdf')
    r=r.rename(columns=colname_mapper)
    r[coverage_col] *= 100

#     r = r.groupby(['coverage', 'duration', 'child_stunting_permanent', 'child_wasting_permanent', 'iron_deficiency_permanent', 'iron_deficiency_mean', 'input_draw']).sum()
    r = r.groupby(index_cols).sum()
    return r

def standardize_shape(data, measure, index_cols):
    measure_data = data.loc[:, [c for c in data.columns if measure in c]]
    index_level = len(index_cols)
#     measure_data = measure_data.stack().reset_index().rename(columns={'level_7': 'label', 0: 'value'})
    measure_data = measure_data.stack().reset_index().rename(
        columns={f'level_{index_level}': 'label', 0: 'value'})
    if 'due_to' in measure:
        measure, cause = measure.split('_due_to_', 1)
        measure_data.loc[:, 'measure'] = measure
        measure_data.loc[:, 'cause'] = cause
    else:
        measure_data.loc[:, 'measure'] = measure  
    measure_data.drop(columns='label', inplace=True)
    
    return measure_data

def get_person_time(data, index_cols):
    pt = standardize_shape(data, 'person_time', index_cols)
    pt = pt.rename(columns={'value': 'person_time'}).drop(columns='measure')
    return pt

def get_treated_days(data, index_cols):
    treated = standardize_shape(data, 'sqlns_treated_days', index_cols)
    treated = treated.rename(columns={'value': 'sqlns_treated_days'}).drop(columns='measure')
    return treated

def get_disaggregated_results(data, cause_names, index_cols):
    
#     global template_cols
    
    deaths = []
    ylls = []
    ylds = []
    dalys = []
#     level = len(index_cols)
    for cause in cause_names:
        if cause in cause_names[:4]:
            deaths.append(standardize_shape(data, f'death_due_to_{cause}', index_cols))
            
            ylls_sub = standardize_shape(data, f'ylls_due_to_{cause}', index_cols)
            ylds_sub = standardize_shape(data, f'ylds_due_to_{cause}', index_cols)
#             dalys_sub = (ylds_sub.set_index([c for c in template_cols if c != 'measure']) + \
#                          ylls_sub.set_index([c for c in template_cols if c != 'measure'])).reset_index()
            dalys_sub = (ylds_sub.set_index(index_cols+['cause']) + \
                         ylls_sub.set_index(index_cols+['cause'])).reset_index()
            dalys_sub['measure'] = 'dalys'
            
            ylls.append(ylls_sub)
            ylds.append(ylds_sub)
            dalys.append(dalys_sub)
        elif cause == 'iron_deficiency':
            ylds_sub = standardize_shape(data, f'ylds_due_to_{cause}', index_cols)     
            dalys_sub = ylds_sub.copy()
            dalys_sub['measure'] = 'dalys'
            
            ylds.append(ylds_sub)
            dalys.append(dalys_sub)
        else: # cause == 'other_causes'
            deaths.append(standardize_shape(data, f'death_due_to_{cause}', index_cols))
            
            ylls_sub = standardize_shape(data, f'ylls_due_to_{cause}', index_cols)
            dalys_sub = ylls_sub.copy()
            dalys_sub['measure'] = 'dalys'
            
            ylls.append(ylls_sub)
            dalys.append(dalys_sub)
    
    death_data = pd.concat(deaths, sort=False)
    yll_data = pd.concat(ylls, sort=False)
    yld_data = pd.concat(ylds, sort=False)
    daly_data = pd.concat(dalys, sort=False)
    
    output = pd.concat([death_data, yll_data, yld_data, daly_data], sort=False)
#     output = output.set_index(template_cols).sort_index()
    output = output.set_index(index_cols + ['cause', 'measure']).sort_index()
    
    return output.reset_index()

def get_all_cause_results(data, index_cols):
    all_cause_data = data[['total_population_dead', 
                           'years_of_life_lost', 
                           'years_lived_with_disability']].rename(
        columns={'total_population_dead': 'death_due_to_all_causes',
                 'years_of_life_lost': 'ylls_due_to_all_causes', 
                 'years_lived_with_disability': 'ylds_due_to_all_causes'})
    
    all_cause_data['dalys_due_to_all_causes'] = (all_cause_data['ylls_due_to_all_causes'] 
                                                 + all_cause_data['ylds_due_to_all_causes'])
    
    return pd.concat([standardize_shape(all_cause_data, column, index_cols)
                      for column in all_cause_data.columns], sort=False)

def get_all_results(data, cause_names, index_cols):
    """
    Get transformed output disaggregated by cause and aggregated over all causes.
    """
    return pd.concat([get_disaggregated_results(data, cause_names, index_cols),
                      get_all_cause_results(data, index_cols)], sort=False)

# def add_person_time_and_treated_days(output, data, index_cols):
#     """
#     Add 'person_time' and 'sqlns_treated_days' columns to the dataframe so we have these data 
#     for each (scenario, draw, cause) combination.
#     """
#     df = output.merge(get_person_time(data), on=index_cols).merge(get_treated_days(data), on=index_cols)
#     return df

def get_transformed_data(data, cause_names, index_cols):
    """
    Transforms the raw output file into "long" form.
    The returned dataframe is that from `get_all_results`, but with 'person_time'
    and 'sqlns_treated_days' columns added so that we have these data for each
    (scenario, draw, cause) combination.
    """
#     global cause_names, join_columns
    
#     r = clean_and_aggregate(output)
    all_results = get_all_results(data, cause_names, index_cols)
    df = all_results.merge(
        get_person_time(data, index_cols), on=index_cols).merge(
        get_treated_days(data, index_cols), on=index_cols)
    return df

def get_averted_results(df, index_cols, coverage_col):
    """
    Add columns for averted results by subtracting from baseline.
    Also adds columns for:
    1. 'value_rate' - Results in rate space (all measures per 100,000 PY).
    2. 'averted_rate' - Averted values in rate space:
        (baseline rate of measure - treatement rate of measure).
    3. 'treated_days_per_averted' - Treatment days per averted measure.
    4. 'treated_days_per_averted_rate' - Treatment days per averted measure, 
        calculated using the averted rates and person time instead of raw counts
        (this will always be slightly smaller than the raw 'treated_days_per_averted'
        values, but the calculation avoids divide-by-zeros at the draw level). 
    """
#     # Original version:
#     bau = df[df.coverage == 0.0].drop(columns=['coverage', 'sqlns_treated_days'])
#     t = pd.merge(df, bau, on=template_cols[1:], suffixes=['', '_bau'])
    bau = df[df[coverage_col] == 0.0].drop(columns=[coverage_col, 'sqlns_treated_days'])
    t = pd.merge(df, bau,
                 on = ['location', 'cause', 'measure'] + [col for col in index_cols if col != coverage_col],
                 suffixes=['', '_bau'])
    
    # Averted raw value
    t['averted'] = t['value_bau'] - t['value']
    
    # Get value per 100,000 PY
    t['value_rate'] = 100_000 * t['value'] / t['person_time']
    
    # Averted value per 100,000 PY:
    t['averted_rate'] = 100_000 * t['value_bau']/t['person_time_bau'] - t['value_rate']
    
    # Treated days per averted DALY/YLL/YLD/death can be multiplied
    #  by cost per day of treatment to compute cost effectiveness.
    # Note that we have 0/0 in baseline - ICER ratio is undefined at 0% coverage.
    t['treated_days_per_averted'] = t['sqlns_treated_days']/t['averted']
    # This is an alternative calculation that is more numerically stable at the draw level.
    # It will always be slightly less than treated_days/averted, but the values are comparable.
    t['treated_days_per_averted_rate'] = 100_000*(t['sqlns_treated_days']/(t['person_time']*t['averted_rate']))
    
    return t

def get_final_table(data, index_cols):
    """
    Aggregate measures over draws to compute the mean and lower 2.5% and upper 97.5% percentiles.
    Uses pandas DataFrame.describe() method, so it also returns median and standard deviation.
    """
    # Group by all index columns except input_draw to aggregate over draws
    aggregate_index = [col for col in index_cols if col != 'input_draw'] + ['cause', 'measure']
    # Original version: g = data.groupby(template_cols[:-1])[[]]
    g = data.groupby(aggregate_index)[['value',
                                          'person_time', 
                                          'sqlns_treated_days',
                                          'averted',
                                          'averted_rate',
                                          'treated_days_per_averted',
                                          'treated_days_per_averted_rate',
                                         ]]\
            .describe(percentiles=[.025, .975]) # returns mean, stdev, median, percentiles .025 & .975
    return g