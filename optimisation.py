"""
This file shows how to do a number of different optimisations - 'one shot' and bootstrapping ;
  also entirely in sample, expanding, and rolling windows

As in chapter 4 of "Systematic Trading" by Robert Carver (www.systematictrading.org)

Required: pandas / numpy, matplotlib

USE AT YOUR OWN RISK! No warranty is provided or implied.

Handling of NAN's and Inf's isn't done here (except within pandas), 
And there is no error handling!

"""

import datetime
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy.optimize import minimize
import random

def pd_readcsv(filename):
    """
    Reads the pandas dataframe from a filename, given the index is correctly labelled
    """

    
    ans=pd.read_csv(filename)
    ans.index=pd.to_datetime(ans['DATETIME'])
    del ans['DATETIME']
    ans.index.name=None
    
    return ans

def correlation_matrix(returns):
    """
    Calcs a correlation matrix using weekly returns from a pandas time series

    We use weekly returns because otherwise end of day effects, especially over time zones, give
    unrealistically low correlations
    
    """
    asset_index=returns.cumsum().ffill()
    asset_index=asset_index.resample('1W') ## Only want index, fill method is irrelevant
    asset_index = asset_index - asset_index.shift(1)

    return asset_index.corr().values
    

def create_dull_pd_matrix(dullvalue=0.0, dullname="A", startdate=pd.datetime(1970,1,1).date(), enddate=datetime.datetime.now().date(), index=None):
    """
    create a single valued pd matrix
    """
    if index is None:
        index=pd.date_range(startdate, enddate)
    
    dullvalue=np.array([dullvalue]*len(index))
    
    ans=pd.DataFrame(dullvalue, index, columns=[dullname])
    
    return ans

def addem(weights):
    ## Used for constraints
    return 1.0 - sum(weights)

def variance(weights, sigma):
    ## returns the variance (NOT standard deviation) given weights and sigma
    return (np.matrix(weights)*sigma*np.matrix(weights).transpose())[0,0]


def neg_SR(weights, sigma, mus):
    ## Returns minus the Sharpe Ratio (as we're minimising)

    """    
    estreturn=250.0*((np.matrix(x)*mus)[0,0])
    variance=(variance(x,sigma)**.5)*16.0
    """
    estreturn=(np.matrix(weights)*mus)[0,0]
    std_dev=(variance(weights,sigma)**.5)

    
    return -estreturn/std_dev


def equalise_vols(returns, default_vol):
    """
    Normalises returns so they have the in sample vol of defaul_vol (annualised)
    Assumes daily returns
    """
    
    factors=(default_vol/16.0)/returns.std(axis=0)
    facmat=create_dull_pd_matrix(dullvalue=factors, dullname=returns.columns, index=returns.index)
    norm_returns=returns*facmat
    norm_returns.columns=returns.columns

    return norm_returns

def markosolver(returns, equalisemeans=False, equalisevols=True, default_vol=0.2, default_SR=1.0):
    """
    Returns the optimal portfolio for the dataframe returns
    
    If equalisemeans=True then assumes all assets have same return if False uses the asset means    
    
    If equalisevols=True then normalises returns to have same standard deviation; the weights returned
       will be 'risk weightings'
       
    Note if usemeans=True and equalisevols=True effectively assumes all assets have same sharpe ratio
    
    """
        
    if equalisevols:
        use_returns=equalise_vols(returns, default_vol)
    else:
        use_returns=returns
    

    ## Sigma matrix 
    sigma=use_returns.cov().values

    ## Expected mean returns    
    if equalisemeans:
        ## Don't use the data - Set to the default Sharpe Ratio
        mus=np.array([(sigma.diagonal()[idx]**.5)*default_SR/16.0 for idx in range(len(use_returns.columns))], ndmin=2).transpose()
        
    else:
        mus=np.array([use_returns[asset_name].mean() for asset_name in use_returns.columns], ndmin=2).transpose()
    
    ## Starting weights
    number_assets=use_returns.shape[1]
    start_weights=[1.0/number_assets]*number_assets
    
    ## Constraints - positive weights, adding to 1.0
    bounds=[(0.0,1.0)]*number_assets
    cdict=[{'type':'eq', 'fun':addem}]
    
    ans=minimize(neg_SR, start_weights, (sigma, mus), method='SLSQP', bounds=bounds, constraints=cdict, tol=0.00001)
        
    return ans['x']




"""
Now we need to do this with expanding or rolling window
"""

"""
Generate the date tuples
"""

def generate_fitting_dates(data, date_method, rollyears=20):
    """
    generate a list 4 tuples, one element for each year in the data
    each tuple contains [fit_start, fit_end, period_start, period_end] datetime objects
    the last period will be a 'stub' if we haven't got an exact number of years
    
    date_method can be one of 'in_sample', 'expanding', 'rolling'
    
    if 'rolling' then use rollyears variable  
    """
    
    start_date=data.index[0]
    end_date=data.index[-1]
    
    ## generate list of dates, one year apart, including the final date
    yearstarts=list(pd.date_range(start_date, end_date, freq="12M"))+[end_date]
   
    ## loop through each period     
    periods=[]
    for tidx in range(len(yearstarts))[1:-1]:
        ## these are the dates we test in
        period_start=yearstarts[tidx]
        period_end=yearstarts[tidx+1]

        ## now generate the dates we use to fit
        if date_method=="in_sample":
            fit_start=start_date
        elif date_method=="expanding":
            fit_start=start_date
        elif date_method=="rolling":
            yearidx_to_use=max(0, tidx-rollyears)
            fit_start=yearstarts[yearidx_to_use]
        else:
            raise Exception("don't recognise date_method %s" % date_method)
            
        if date_method=="in_sample":
            fit_end=end_date
        elif date_method in ['rolling', 'expanding']:
            fit_end=period_start
        else:
            raise Exception("don't recognise date_method %s " % date_method)
        
        periods.append([fit_start, fit_end, period_start, period_end])

    ## give the user back the list of periods
    return periods


"""
Now do some fitting

Before we do that we need a bootstrap fitter
"""

def bootstrap_portfolio(returns_to_bs, monte_carlo=200, monte_length=250, equalisemeans=False, equalisevols=True, default_vol=0.2, default_SR=1.0):
    
    """
    Given dataframe of returns; returns_to_bs, performs a bootstrap optimisation
    
    We run monte_carlo numbers of bootstraps
    Each one contains monte_length days drawn randomly, with replacement 
    (so *not* block bootstrapping)
    
    The other arguments are passed to the optimisation function markosolver
    
    Note - doesn't deal gracefully with missing data. Will end up downweighting stuff depending on how
      much data is missing in each boostrap. You'll need to think about how to solve this problem. 
    
    """
    
    weightlist=[]
    for unused_index in range(monte_carlo):
        bs_idx=[int(random.uniform(0,1)*len(returns_to_bs)) for i in range(monte_length)]
        
        returns=returns_to_bs.iloc[bs_idx,:] 
        weight=markosolver(returns, equalisemeans=equalisemeans, equalisevols=equalisevols, default_vol=default_vol, default_SR=default_SR)
        weightlist.append(weight)
        
    theweights_mean=list(np.mean(weightlist, axis=0))
    return theweights_mean

def optimise_over_periods(data, date_method, fit_method, rollyears=20, equalisemeans=False, equalisevols=True, 
                          monte_carlo=200, monte_length=250):
    """
    Do an optimisation
    
    Returns data frame of weights
    
    Note if fitting in sample weights will be somewhat boring
    
    Doesn't deal with eg missing data in certain subperiods
    
    
    """
    
    ## Get the periods
    fit_periods=generate_fitting_dates(data, date_method, rollyears=rollyears)
    
    ## Do the fitting
    ## Build up a list of weights, which we'll concat
    weight_list=[]
    for fit_tuple in fit_periods:
        ## Fit on the slice defined by first two parts of the tuple
        period_subset_data=data[fit_tuple[0]:fit_tuple[1]]
        
        ## Can be slow, if bootstrapping, so indicate where we are
        
        print "Fitting data for %s to %s" % (str(fit_tuple[2]), str(fit_tuple[3]))
        
        if fit_method=="one_period":
            weights=markosolver(period_subset_data, equalisemeans=equalisemeans, equalisevols=equalisevols)
        elif fit_method=="bootstrap":
            weights=bootstrap_portfolio(period_subset_data, equalisemeans=equalisemeans, 
                                        equalisevols=equalisevols, monte_carlo=monte_carlo, 
                                        monte_length=monte_length)
        else:
            raise Exception("Fitting method %s unknown" % fit_method)
        
        ## We adjust dates slightly to ensure no overlaps
        dindex=[fit_tuple[2]+datetime.timedelta(seconds=1), fit_tuple[3]-datetime.timedelta(seconds=1)]
        
        ## create a double row to delineate start and end of test period
        weight_row=pd.DataFrame([weights]*2, index=dindex, columns=data.columns)
        
        weight_list.append(weight_row)
        
    weight_df=pd.concat(weight_list, axis=0)
    
    return weight_df

## Get the data

filename="/home/rsc/workspace/systematictradingexamples/assetprices.csv"
data=pd_readcsv(filename)

## Let's do some optimisation
## Feel free to play with these

mat1=optimise_over_periods(data, "expanding", "one_shot", equalisevols=True)
mat1.plot()
plt.show()

## This will take longer
## Reduce the bootstraps for speed (reduce monte_carlo) but will get noisier results
mat2=optimise_over_periods(data, "expanding", "bootstrap", equalisevols=True, monte_carlo=200)
mat2.plot()
plt.show()