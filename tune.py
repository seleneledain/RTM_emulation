''' 
Perform hyperparameter tuning for a RTM-inversion model

@Selene Ledain
'''
# Read model architecture to tune
# Read parameter grid
# What default values and data path to use? Should put in the yaml anyways?
# Send parameters to train.py
# Save results somehow (.csv?)

from argparse import ArgumentParser
import yaml
from typing import Dict, Tuple, Union, Any
from datetime import datetime
import os
import csv
from subprocess import run, PIPE
import itertools



def load_config(config_path: str) -> Dict:
  ''' 
  Load configuration file

  :param config_path: path to yaml file
  :returns: dictionary of parameters
  '''
  with open(config_path, "r") as config_file:
      config = yaml.safe_load(config_file)
  return config


def update_config(names: tuple, values: list) -> Dict:
  '''
  Update the config with a specific hyperparameter setup

  :params names: hypereparameter names
  :params values: values to set
  '''
  for i, name in enumerate(names):
    if name=='lr':
      config['Model']['optim']['lr'] = values[i]
    else:
      config['Model'][name] = values[i]
  
  return config


def save_updated_config(updated_config, temp_config_path):
  ''' 
  Temporarily save config file fo hyperparam config

  :params updated_config: new config dict
  :param temp_config_path: path
  '''
  with open(temp_config_path, 'w') as temp_config_file:
      yaml.dump(updated_config, temp_config_file)
  return temp_config_path


def tune_model(config: dict) -> None:
  ''' 
  Tune model based on grid of hyperparameter values

  :param config: dictionary of configuration parameters
  '''
  # Get hyperparam grid
  hyperparam_grid = config['Grid']
  hyperparam_combinations = list(itertools.product(*hyperparam_grid.values()))

  # Create a directory to store results
  results_dir = 'tuning_results/'
  os.makedirs(results_dir, exist_ok=True)

  # Open a CSV file to store the results
  results_file = os.path.join(results_dir, config['Model']['name'] + '_' + datetime.now().strftime("%Y%m%d_%H%M%S") + '_tuning.csv')
  with open(results_file, 'w', newline='') as csvfile:
    fieldnames = list(hyperparam_grid.keys()) +['Test_RMSE']
    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
    writer.writeheader()

    # Iterate over hyperparameter combinations
    for hyperparam_values in hyperparam_combinations:
      # Update the hyperparameters in the config
      config = update_config(hyperparam_grid.keys(), hyperparam_values)
    
      # Save the updated config to a temporary file
      temp_config_path = os.path.join(results_dir, 'temp_config.yaml')
      temp_config_path = save_updated_config(config, temp_config_path)

      # Call train.py with the updated config
      train_cmd = ['python', 'train.py', temp_config_path]
      process = run(train_cmd, stdout=PIPE, stderr=PIPE, universal_newlines=True)

      # Extract the test score from the output
      error_lines = process.stderr.split('\n')
      output_lines = process.stdout.split('\n')
      test_rmse_line = [line for line in output_lines if 'Test RMSE' in line]
      test_rmse = float(test_rmse_line[0].split(': ')[1]) if test_rmse_line else None

      # Write the results to the CSV file
      row_dict = {h: hyperparam_values[i] for i, h in enumerate(hyperparam_grid.keys())}
      row_dict['Test_RMSE'] = test_rmse
      writer.writerow(row_dict)
  
  # Delete the temporary config file
  os.remove(temp_config_path)

  print(f'Tuning results saved in {results_file}')
  return


if __name__ == "__main__":
  parser = ArgumentParser()
  parser.add_argument('tune_settings', type = str, metavar='path/to/setting.yaml', help='yaml with settings for hyperparam tuning')
  args = parser.parse_args()

  config = load_config(args.tune_settings)
  tune_model(config)