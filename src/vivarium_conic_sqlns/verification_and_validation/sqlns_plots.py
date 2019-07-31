"""
Module for plotting output of SQLNS model.
Code was copied from Nathaniel's notebook 2019_07_25_validation_with_treated_days.ipynb
on 2019-07-30. It may or may not work as is.

Hmm, I successfully imported the module into a notebook, and it looks like it ran all the
code and displayed the final graph. I think what we want to do is get rid of the
@interact property on the functions, and explicitly call interact() from within the notebook.

Also, it would be better to separate the data transformation (particularly the aggregation,
which takes awhile) from the plotting. To do so, we probably have to rewrite the plotting
functions to accept the appropriate dataframe as a parameter, and use the `fixed` feature
in ipython widgets to fix the dataframe parameter in the interactive plots.
"""

import pandas as pd
import matplotlib.pyplot as plt
from ipywidgets import interact, IntSlider

from sqlns_output_processing import *

result_dir = '/share/costeffectiveness/results/sqlns/presentation/nigeria/2019_07_30_00_01_45'

# Load outpt data - as of 2019-07-25 there are random seeds missing
raw_output = load_output(result_dir, 'output.hdf')

# Raw data aggregated by random seed, with intervention columns renamed
r = clean_and_aggregate(raw_output)

# Get results disaggregated by cause and aggregated over all causes
output = get_all_results(r, cause_names)

# join_columns = [c for c in template_cols if c not in ['cause', 'measure']]
# Add person_time and sqlns_treated_days columns for each (scenario, draw, cause) combination
df = output.merge(get_person_time(r), on=join_columns).merge(get_treated_days(r), on=join_columns)


## The previous 3 lines can be replaced with this new function:
# df = get_transformed_data(raw_output)

# Add columns for averted results
averted_df = get_averted_results(df)

# Aggregate over draws to compute mean and lower & upper percentiles
# This code may take a couple minutes to run
aggregated_results_df = get_final_table(averted_df)

# Get lists of draws, measures, and costs for interactive plots
draws = r.reset_index().input_draw.unique()
measures = output.measure.unique()
averted_cause_list = averted_df.cause.unique()
cost_slider = IntSlider(value=50, min=5, max=100, step=5, continuous_update=False)

# Constants to use in plotting code
days_per_year = 365.25
years_of_simulation = 5


# Create a pandas IndexSlice object to easily multi-index the original dataframe
idx = pd.IndexSlice
r.loc[idx[:, 365.25, False, False, False, 0.895, 55],
      ['years_of_life_lost', 'years_lived_with_disability', 'person_time']].reset_index()

@interact()
def plot_total_dalys_by_draw(duration=[365.25, 730.50],
                    cgf_permanent=[False, True],
                    iron_permanent=[False, True],
                    iron_mean=[0.895, 4.475, 8.950],
                    input_draw = draws,
                  ):
    
    data = r.loc[idx[:, duration, cgf_permanent, cgf_permanent, iron_permanent, iron_mean, input_draw],
      ['years_of_life_lost', 'years_lived_with_disability', 'person_time']].reset_index()
    
    fig, ax = plt.subplots(2,2, figsize=(12,8))
    
    xx = data['coverage']
    
    measures_short_names = {'years_of_life_lost': 'YLL', 'years_lived_with_disability': 'YLD'}

    for i, (measure, short_name) in enumerate(measures_short_names.items()):
        ax[i,0].plot(xx, data[measure], '-o')
        ax[i,1].plot(xx, 100_000*data[measure] / data['person_time'], '-o', color='orange')
    
        ax[i,0].set_title(f'Total {short_name} count vs. coverage', fontsize=20)
        ax[i,0].set_xlabel('Program Coverage (%)', fontsize=16)
        ax[i,0].set_ylabel(f'{short_name}s', fontsize=20)
        ax[i,0].grid()
#         ax[i,0].legend(loc=(0.8, -.25), fontsize=14)

        ax[i,1].set_title(f'Total {short_name} rate vs. coverage', fontsize=20)
        ax[i,1].set_xlabel('Program Coverage (%)', fontsize=16)
        ax[i,1].set_ylabel(f'{short_name}s per 100,000 person years', fontsize=12)
        ax[i,1].grid()
        
    fig.tight_layout()


@interact()
def plot_treated_days_by_draw(duration=[365.25, 730.50],
                    cgf_permanent=[False, True],
                    iron_permanent=[False, True],
                    iron_mean=[0.895, 4.475, 8.950],
                    input_draw = draws,
                  ):
    
    data = r.loc[idx[:, duration, cgf_permanent, cgf_permanent, iron_permanent, iron_mean, input_draw],
      ['sqlns_treated_days', 'total_population_living', 'total_population_tracked', 'person_time']].reset_index()
    
    fig, ax = plt.subplots(1,2, figsize=(13,6))
    
    xx = data['coverage']
    

    ax[0].plot(xx, data['sqlns_treated_days'] / days_per_year, '-o')
#     # This is computing something like "average person years per treatment year for a treated simulant",
#     # then multiplying that by the number of treated years over the number of person years.
#     ax[1].plot(xx,
#                (data['total_population_living'] / data['total_population_tracked']) *
#                years_of_simulation * data['sqlns_treated_days'] / (duration * data['person_time']),
#                '-o', color='orange')
    ax[1].plot(xx, data['sqlns_treated_days'] / (duration * data['total_population_tracked']),
               '-o', color='orange')

    ax[0].set_title('Treated years vs. coverage', fontsize=20)
    ax[0].set_xlabel('Program Coverage (%)', fontsize=16)
    ax[0].set_ylabel('SQ-LNS treated years', fontsize=20)
    ax[0].grid()
#         ax[i,0].legend(loc=(0.8, -.25), fontsize=14)

    ax[1].set_title('Estimated fraction of\npopulation treated vs. coverage', fontsize=20)
    ax[1].set_xlabel('Program Coverage (%)', fontsize=16)
#     ax[1].set_ylabel('(survival-rate)\nx (simulation-duration / treatment-duration)\nx (treated-years / person-years)', fontsize=12)
    ax[1].set_ylabel('sqlns_treated_time /\n(treatment_duration x population_tracked)', fontsize=12)
    ax[1].grid()
        
    fig.tight_layout()
    
    
@interact()
def plot_cause_spceific_dalys_by_draw(duration=[365.25, 730.50],
                    cgf_permanent=[False, True],
                    iron_permanent=[False, True],
                    iron_mean=[0.895, 4.475, 8.950],
                    input_draw = df.input_draw.unique(),
                    measure = df.measure.unique(),
                    include_other_causes=True,
                    include_all_causes=False,
                  ):
    
    data = df.loc[(df.duration == duration)
                  & (df.child_stunting_permanent == cgf_permanent)
                  & (df.child_wasting_permanent == cgf_permanent)
                  & (df.iron_deficiency_permanent == iron_permanent)
                  & (df.iron_deficiency_mean == iron_mean)
                  & (df.input_draw == input_draw)
                  & (df.measure == measure)]
    
    fig, ax = plt.subplots(1,2, figsize=(18,8))
    
    # 'other_causes' value is much higher - can omit by indexing with [:-1]
    displayed_causes = cause_names if include_other_causes else cause_names[:-1]
    if include_all_causes:
        displayed_causes = displayed_causes + ['all_causes']
        
    for cause in displayed_causes:
        data_sub = data.loc[data.cause == cause]
        
        xx = data_sub['coverage']
        value = data_sub['value']
        value_over_pt = 100_000* data_sub['value'] / data_sub['person_time']
        
        ax[0].plot(xx, value, '-o', label=cause)
        ax[1].plot(xx, value_over_pt, '-o')
        
    singular_measure = measure if measure=='death' else measure[:-1]
    plural_measure = 'deaths' if measure=='death' else measure
    
    ax[0].set_title(f'{singular_measure.upper()} count by disease vs. coverage', fontsize=20)
    ax[0].set_xlabel('Program Coverage (%)', fontsize=20)
    ax[0].set_ylabel(f'{plural_measure.upper()}', fontsize=20)
    ax[0].grid()
    ax[0].legend(loc=(0.9, -.3))
    
    ax[1].set_title(f'{singular_measure.upper()} rate by disease vs. coverage', fontsize=20)
    ax[1].set_xlabel('Program Coverage (%)', fontsize=20)
    ax[1].set_ylabel(f'{plural_measure.upper()} per 100,000 person years', fontsize=20)
    ax[1].grid()
    
@interact()
def plot_aggregated_averted_rates(duration=[365.25, 730.50],
                       cgf_permanent=[False, True],
                       iron_permanent=[False, True],
                       iron_mean=[0.895, 4.475, 8.950],
                       measure = measures,
                       include_other_causes=False,
                       include_all_causes=False,
                      ):
    
    df = aggregated_results_df.reset_index()
    
    data = df.loc[(df.duration == duration)
                  & (df.child_stunting_permanent == cgf_permanent)
                  & (df.child_wasting_permanent == cgf_permanent)
                  & (df.iron_deficiency_permanent == iron_permanent)
                  & (df.iron_deficiency_mean == iron_mean)
                  & (df.measure == measure)]
    
    plt.figure(figsize=(12, 8))
    
    # 'other_causes' value is much higher - can omit by indexing with [:-1]
    displayed_causes = cause_names if include_other_causes else cause_names[:-1]
    if include_all_causes:
        displayed_causes = displayed_causes + ['all_causes']
        
    for cause in displayed_causes:
        data_sub = data.loc[data.cause == cause]
        
        xx = data_sub['coverage']
        mean = data_sub[('averted_rate', 'mean')]
        lb = data_sub[('averted_rate', '2.5%')]
        ub = data_sub[('averted_rate', '97.5%')]
        
        plt.plot(xx, mean, '-o', label=cause)
        plt.fill_between(xx, lb, ub, alpha=0.1)
    
    plt.title('Nigeria')
    plt.xlabel('Program Coverage (%)')
    plt.ylabel(f'{measure.upper()} Averted (per 100,000 PY)')
    plt.legend(loc=(1.05, .05))
    plt.grid()
    
@interact()
def plot_dalys_per_1e5_py(duration=[365.25, 730.50],
                       cgf_permanent=[False, True],
                       iron_permanent=[False, True],
                       iron_mean=[0.895, 4.475, 8.950],
                        include_other_causes=False):
    
    df = aggregated_results_df.reset_index()
    
    data = df.loc[(df.duration == duration)
                  & (df.child_stunting_permanent == cgf_permanent)
                  & (df.child_wasting_permanent == cgf_permanent)
                  & (df.iron_deficiency_permanent == iron_permanent)
                  & (df.iron_deficiency_mean == iron_mean)
                  & (df.measure == 'dalys')]
    
    plt.figure(figsize=(12, 8))
    
    # 'other_causes' value is much higher - can omit by indexing with [:-1]
    displayed_causes = cause_names if include_other_causes else cause_names[:-1]
    for cause in displayed_causes:
        data_sub = data.loc[data.cause == cause]
        
        xx = data_sub['coverage']
        mean_per_py = data_sub[('value', 'mean')]
        lb = data_sub[('value', '2.5%')]
        ub = data_sub[('value', '97.5%')]
        
        plt.plot(xx, mean_per_py, '-o', label=cause)
        plt.fill_between(xx, lb, ub, alpha=0.1)
    
    plt.title('Nigeria')
    plt.xlabel('Program Coverage (%)')
    plt.ylabel('DALYs per 100,000 PY')
    plt.legend(loc=(1.05, .05))
    plt.grid()
    
@interact()
def plot_icers(duration=[365.25, 730.50],
                    cgf_permanent=[False, True],
                    iron_permanent=[False, True],
                    iron_mean=[0.895, 4.475, 8.950],
                              measure=measures,
                              cause=averted_cause_list,
                              cost_per_py=cost_slider,
                  ):
    
    data = aggregated_results_df.reset_index()
    
    data = data.loc[(data.duration == duration)
                  & (data.child_stunting_permanent == cgf_permanent)
                  & (data.child_wasting_permanent == cgf_permanent)
                  & (data.iron_deficiency_permanent == iron_permanent)
                  & (data.iron_deficiency_mean == iron_mean)
                  & (data.cause == cause)
                  & (data.measure == measure)]
    
    fig, ax = plt.subplots(2,2, figsize=(14,9))
    
    xx = data['coverage']
    
    # Plot cost vs. coverage
    mean = cost_per_py * data[('sqlns_treated_days', 'mean')] / days_per_year
    lb = cost_per_py * data[('sqlns_treated_days', '2.5%')] / days_per_year
    ub = cost_per_py * data[('sqlns_treated_days', '97.5%')] / days_per_year
    ax[0,0].plot(xx, mean, '-o')
    ax[0,0].fill_between(xx, lb, ub, alpha=0.8)
    
    # Plot averted measure vs. coverage
    mean = data[('averted', 'mean')]
    lb = data[('averted', '2.5%')]
    ub = data[('averted', '97.5%')]
    ax[1,0].plot(xx, mean, '-o', color='orange')
    ax[1,0].fill_between(xx, lb, ub, alpha=0.1, color='orange')
    
    # Plot ICERs calculated using raw values
    mean = cost_per_py * data[('treated_days_per_averted', 'mean')] / days_per_year
    lb = cost_per_py * data[('treated_days_per_averted', '2.5%')] / days_per_year
    ub = cost_per_py * data[('treated_days_per_averted', '97.5%')] / days_per_year
    ax[0,1].plot(xx, mean, '-o', color='green')
    ax[0,1].fill_between(xx, lb, ub, alpha=0.1, color='green')
    
    # Plot ICERs calculated using rates
    mean = cost_per_py * data[('treated_days_per_averted_rate', 'mean')] / days_per_year
    lb = cost_per_py * data[('treated_days_per_averted_rate', '2.5%')] / days_per_year
    ub = cost_per_py * data[('treated_days_per_averted_rate', '97.5%')] / days_per_year
    ax[1,1].plot(xx, mean, '-o', color='green')
    ax[1,1].fill_between(xx, lb, ub, alpha=0.1, color='green')

    ## Label the plots
    
    ax[0,0].set_title('Total cost vs. coverage', fontsize=16)
    ax[0,0].set_xlabel('Program Coverage (%)', fontsize=12)
    ax[0,0].set_ylabel('Cost of SQ-LNS\ntreatment ($)', fontsize=16)
    ax[0,0].grid()
#         ax[i,0].legend(loc=(0.8, -.25), fontsize=14)

    ax[1,0].set_title(f'Averted {measure} vs. coverage', fontsize=16)
    ax[1,0].set_xlabel('Program Coverage (%)', fontsize=12)
    ax[1,0].set_ylabel(f'Averted {measure}', fontsize=16)
    ax[1,0].grid()

    ax[0,1].set_title('Cost effectiveness (ICERs)\nvs. coverage', fontsize=16)
    ax[0,1].set_xlabel('Program Coverage (%)', fontsize=12)
    ax[0,1].set_ylabel(f'Cost per averted {measure}', fontsize=12)
    ax[0,1].grid()
    
    ax[1,1].set_title('Cost effectiveness (ICERs)\nvs. coverage', fontsize=16)
    ax[1,1].set_xlabel('Program Coverage (%)', fontsize=12)
    ax[1,1].set_ylabel(f'Cost per averted {measure}\n(calculated using rate difference)', fontsize=12)
    ax[1,1].grid()
        
    fig.tight_layout()