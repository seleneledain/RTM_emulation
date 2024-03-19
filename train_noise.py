'''
Pass multiple config files and call the training script for each model

@author Selene Ledain
'''

import os
import yaml
from train import load_config, train_model
from test import prepare_data
from sklearn.metrics import mean_squared_error
import copy 
import pickle
import pandas as pd
import matplotlib.pyplot as plt

def test_model(config: dict) -> None:
    ''' 
    Test model on a dataset and get scores

    :param config: dictionary of configuration parameters
    '''

    #############################################
    # DATA
    X_test, y_test = prepare_data(config=config)

    #############################################
    # MODEL
    save_model = config['Model'].pop('save')
    model_name = config['Model']['name']
    model_filename = config['Model'].pop('save_path') 
    with open(model_filename, 'rb') as f:
      model = pickle.load(f)

    #############################################
    # TEST
    if model_name == 'GPR': # Active learning
      y_pred, y_std = model.predict(X_test, return_std=True)
      test_rmse = mean_squared_error(y_test, y_pred, squared=False)
      return model_name, test_rmse, y_std
    else: 
      y_pred = model.predict(X_test=X_test)
      test_rmse = mean_squared_error(y_test, y_pred, squared=False)
      return model_name, test_rmse, None 


if __name__ == "__main__":

    config_path = 'configs/config_GPR.yaml'

    noise_levels = [1, 3, 5, 10, 15, 20, 25, 30, 40, 50]
    noise_types = ['additive', 'multiplicative', 'combined', 'inverse', 'inverse_combined']

    results = {noise_type: {'rmse': [], 'std': []} for noise_type in noise_types}

    for noise_type in noise_types:
      for noise_level in noise_levels:
        print(f'Training with noise {noise_level}% {noise_type}')

        # Modify config: pass data with noise, change model name
        config = load_config(config_path)
        config['Model']['save_path'] = config['Model']['save_path'].split('.pkl')[0] + f'_{noise_type}{noise_level}.pkl'
        config['Data']['data_path'] = [f.split('.pkl')[0] + f'_{noise_type}{noise_level}.pkl' for f in config['Data']['data_path']]
        config_test = copy.deepcopy(config)

        train_model(config)
        model_name, test_rmse, y_std = test_model(config_test)
        #results.append((model_name + f'_{noise_type}{noise_level}', test_rmse, y_std))
        results[noise_type]['rmse'].append(test_rmse)
        results[noise_type]['std'].append(y_std)  
 
    # Save results to Excel
    data = {'Noise Level': noise_levels}
    for noise_type, values in results.items():
        data[f'{noise_type}_rmse'] = values['rmse']
        data[f'{noise_type}_std'] = values['std']

    df_results = pd.DataFrame(data)
    df_results.to_excel('../results/noise_results_GPR.xlsx', index=False)

    # Plot
    plt.figure(figsize=(10, 6))
    for noise_type in noise_types:
        plt.plot(df_results['Noise Level'], df_results[f'{noise_type}_rmse'], label=noise_type)

    plt.xlabel('Noise Level')
    plt.ylabel('Test RMSE')
    plt.title('GPR with noise RMSE')
    plt.legend()
    plt.savefig('../results/noise_plot_GPR.png')  # Save plot as image