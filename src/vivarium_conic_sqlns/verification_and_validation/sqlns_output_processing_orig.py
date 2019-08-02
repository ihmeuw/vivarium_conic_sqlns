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

cause_names = ['lower_respiratory_infections', 'measles', 'diarrheal_diseases', 
               'protein_energy_malnutrition', 'iron_deficiency', 'other_causes']

risk_names = ['anemia', 'child_stunting', 'child_wasting']

template_cols = ['coverage', 'duration', 'child_stunting_permanent', 
                 'child_wasting_permanent', 'iron_deficiency_permanent', 
                 'iron_deficiency_mean', 'cause', 'measure', 'input_draw']

join_columns = [c for c in template_cols if c not in ['cause', 'measure']]

def load_output(path, filename):
    """Loads output file."""
    r = pd.read_hdf(f'{path}/{filename}')
    return r

# note that we have applied coefficient of variation as constant with different sqlns effect on iron deficiency
def clean_and_aggregate(r):
    """
    Does the following "cleaning" steps, then sums over random seeds.
    Cleaning steps:
        1. Rename intervention columns with shorter names.
        2. Multiply coverage by 100 to convert to percent.
    """
#     r = pd.read_hdf(path + 'nigeria/2019_07_18_13_20_17/output.hdf')
    r=r.rename(columns={'sqlns.effect_on_child_stunting.permanent': 'child_stunting_permanent',
                      'sqlns.effect_on_child_wasting.permanent': 'child_wasting_permanent',
                      'sqlns.effect_on_iron_deficiency.permanent': 'iron_deficiency_permanent',
                      'sqlns.effect_on_iron_deficiency.mean': 'iron_deficiency_mean',
                      'sqlns.program_coverage': 'coverage',
                      'sqlns.duration': 'duration'})
    r['coverage'] *= 100
#     # The 'sqlns_treated_days' column got subtracted in the wrong order for the 2019_07_23_10_57_25 run:
#     r['sqlns_treated_days'] = -1 * r['sqlns_treated_days'] # This line should be deleted once the code is fixed
    r = r.groupby(['coverage', 'duration', 'child_stunting_permanent', 'child_wasting_permanent', 'iron_deficiency_permanent', 'iron_deficiency_mean', 'input_draw']).sum()
    return r

def standardize_shape(data, measure):
    measure_data = data.loc[:, [c for c in data.columns if measure in c]]
    measure_data = measure_data.stack().reset_index().rename(columns={'level_7': 'label', 0: 'value'})
    if 'due_to' in measure:
        measure, cause = measure.split('_due_to_', 1)
        measure_data.loc[:, 'measure'] = measure
        measure_data.loc[:, 'cause'] = cause
    else:
        measure_data.loc[:, 'measure'] = measure  
    measure_data.drop(columns='label', inplace=True)
    
    return measure_data

def get_person_time(data):
    pt = standardize_shape(data, 'person_time')
    pt = pt.rename(columns={'value': 'person_time'}).drop(columns='measure')
    return pt

def get_treated_days(data):
    treated = standardize_shape(data, 'sqlns_treated_days')
    treated = treated.rename(columns={'value': 'sqlns_treated_days'}).drop(columns='measure')
    return treated

def get_disaggregated_results(data, cause_names):
    
    global template_cols
    
    deaths = []
    ylls = []
    ylds = []
    dalys = []
    for cause in cause_names:
        if cause in cause_names[:4]:
            deaths.append(standardize_shape(data, f'death_due_to_{cause}'))
            
            ylls_sub = standardize_shape(data, f'ylls_due_to_{cause}')
            ylds_sub = standardize_shape(data, f'ylds_due_to_{cause}')
            dalys_sub = (ylds_sub.set_index([c for c in template_cols if c != 'measure']) + \
                         ylls_sub.set_index([c for c in template_cols if c != 'measure'])).reset_index()
            dalys_sub['measure'] = 'dalys'
            
            ylls.append(ylls_sub)
            ylds.append(ylds_sub)
            dalys.append(dalys_sub)
        elif cause == 'iron_deficiency':
            ylds_sub = standardize_shape(data, f'ylds_due_to_{cause}')     
            dalys_sub = ylds_sub.copy()
            dalys_sub['measure'] = 'dalys'
            
            ylds.append(ylds_sub)
            dalys.append(dalys_sub)
        else: # cause == 'other_causes'
            deaths.append(standardize_shape(data, f'death_due_to_{cause}'))
            
            ylls_sub = standardize_shape(data, f'ylls_due_to_{cause}')
            dalys_sub = ylls_sub.copy()
            dalys_sub['measure'] = 'dalys'
            
            ylls.append(ylls_sub)
            dalys.append(dalys_sub)
    
    death_data = pd.concat(deaths, sort=False)
    yll_data = pd.concat(ylls, sort=False)
    yld_data = pd.concat(ylds, sort=False)
    daly_data = pd.concat(dalys, sort=False)
    
    output = pd.concat([death_data, yll_data, yld_data, daly_data], sort=False)
    output = output.set_index(template_cols).sort_index()
    
    return output.reset_index()

def get_all_cause_results(data):
    all_cause_data = data[['total_population_dead', 
                           'years_of_life_lost', 
                           'years_lived_with_disability']].rename(
        columns={'total_population_dead': 'death_due_to_all_causes',
                 'years_of_life_lost': 'ylls_due_to_all_causes', 
                 'years_lived_with_disability': 'ylds_due_to_all_causes'})
    
    all_cause_data['dalys_due_to_all_causes'] = (all_cause_data['ylls_due_to_all_causes'] 
                                                 + all_cause_data['ylds_due_to_all_causes'])
    
    return pd.concat([standardize_shape(all_cause_data, column) for column in all_cause_data.columns], sort=False)

def get_all_results(data, cause_names):
    """
    Get transformed output disaggregated by cause and aggregated over all causes.
    """
    return pd.concat([get_disaggregated_results(data, cause_names), get_all_cause_results(data)], sort=False)

# def add_person_time_and_treated_days(output, data, join_columns):
#     """
#     Add 'person_time' and 'sqlns_treated_days' columns to the dataframe so we have these data 
#     for each (scenario, draw, cause) combination.
#     """
#     df = output.merge(get_person_time(data), on=join_columns).merge(get_treated_days(data), on=join_columns)
#     return df

def get_transformed_data(output):
    """
    Transforms the raw output file into "long" form.
    The returned dataframe is that from `get_all_results`, but with 'person_time'
    and 'sqlns_treated_days' columns added so that we have these data for each
    (scenario, draw, cause) combination.
    """
    global cause_names, join_columns
    
    r = clean_and_aggregate(output)
    all_results = get_all_results(r, cause_names)
    df = all_results.merge(get_person_time(r), on=join_columns).merge(get_treated_days(r), on=join_columns)
    return df

def get_averted_results(df):
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
    bau = df[df.coverage == 0.0].drop(columns=['coverage', 'sqlns_treated_days'])
    t = pd.merge(df, bau, on=template_cols[1:], suffixes=['', '_bau'])
    
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

def get_final_table(data):
    """
    Aggregate measures over draws to compute the mean and lower 2.5% and upper 97.5% percentiles.
    Uses pandas DataFrame.describe() method, so it also returns median and standard deviation.
    """
    # Group by all index columns except input_draw to aggregate over draws
    g = data.groupby(template_cols[:-1])[['value',
                                          'person_time', 
                                          'sqlns_treated_days',
                                          'averted',
                                          'averted_rate',
                                          'treated_days_per_averted',
                                          'treated_days_per_averted_rate',
                                         ]]\
            .describe(percentiles=[.025, .975]) # returns mean, stdev, median, percentiles .025 & .975
    return g