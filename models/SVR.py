'''
Support Vector Regression model to perform a RTM inversion

@author Selene Ledain
'''

from sklearn.model_selection import cross_val_score, KFold
from sklearn.svm import SVR
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score
import pandas as pd
from typing import Optional
import pickle
import numpy as np
from tqdm import tqdm

class SVRReg(SVR):
    def __init__(self, kernel='rbf', degree=3, gamma='scale', coef0=0.0, tol=0.001, C=1.0, epsilon=0.1, shrinking=True, cache_size=200, verbose=False, max_iter=-1, k_folds: Optional[int] = 5):
        '''
        Support Vector Regression model

        :param kernel: Specifies the kernel type ('linear', 'poly', 'rbf', 'sigmoid', 'precomputed').
        :param degree: Degree of the polynomial kernel function ('poly').
        :param gamma: Kernel coefficient for 'rbf', 'poly', and 'sigmoid'.
        :param coef0: Independent term in the kernel function ('poly' and 'sigmoid').
        :param tol: Tolerance for stopping criterion.
        :param C: Regularization parameter.
        :param epsilon: Epsilon in the epsilon-SVR model.
        :param shrinking: Whether to use the shrinking heuristic.
        :param cache_size: Specify the size of the kernel cache.
        :param verbose: Enable verbose output.
        :param max_iter: Hard limit on iterations within solver, or -1 for no limit.
        :param k_folds: Number of folds for cross-validation
        '''
        super().__init__(
            kernel=kernel,
            degree=degree,
            gamma=gamma,
            coef0=coef0,
            tol=tol,
            C=C,
            epsilon=epsilon,
            shrinking=shrinking,
            cache_size=cache_size,
            verbose=verbose,
            max_iter=max_iter
        )
        self.k_folds = k_folds

    def fit(self, X: np.array, y: np.array) -> None:
        '''
        Fit the model on the training set, using k-fold cross-validation if possible

        :param X: Training data
        :param y: Training labels
        '''
        if self.k_folds == 0:
            # If k_folds is 0, perform standard training without k-fold cross-validation
            super().fit(X, y)
        else:
            # Perform k-fold cross-validation on the training data
            kf = KFold(n_splits=self.k_folds, shuffle=True, random_state=None)  # Set random_state as needed

            # List to store cross-validation RMSE scores
            cv_rmse_scores = []

            # Loop through each fold
            for train_idx, val_idx in tqdm(kf.split(X), desc='Training CV fold'):
                X_train_fold, X_val_fold = X[train_idx], X[val_idx]
                y_train_fold, y_val_fold = y[train_idx], y[val_idx]

                # Fit the model on the training fold
                super().fit(X_train_fold, y_train_fold)

                # Make predictions on the validation fold
                y_val_pred = super().predict(X_val_fold)

                # Calculate and store RMSE for the current fold
                fold_rmse = mean_squared_error(y_val_fold, y_val_pred)**0.5
                cv_rmse_scores.append(fold_rmse)

            # Print cross-validation results
            print(f'Cross-Validation RMSE for each fold: {cv_rmse_scores}')
            print(f'Mean CV RMSE: {sum(cv_rmse_scores)/len(cv_rmse_scores)}')

    def predict(self, X_test: np.array) -> np.array:
        '''
        Make predictions on the test set

        :param X_test: Test data
        '''
        # Make predictions on the testing set
        return super().predict(X_test)


    def test_scores(self, y_test: np.array, y_pred: np.array, dataset: str):
        '''
        Compute scores on the test set

        :param y_test: test labels
        :param y_pred: test predictions
        :param dataset: dataset name
        '''

        # Compute different scores on the test set
        test_rmse = mean_squared_error(y_test, y_pred, squared=False)
        test_mae = mean_absolute_error(y_test, y_pred)
        test_r2 = r2_score(y_test, y_pred)
        slope, intercept = np.polyfit(y_test.flatten(), y_pred.flatten(), 1)
        rmselow = mean_squared_error(y_test[y_test<3], y_pred[y_test<3], squared=False)
        fabio = abs(np.mean(y_test-y_pred)) + np.std(y_test-y_pred) - np.sqrt(np.cov(y_test.flatten(), y_pred.flatten())[0,1])
        print(f'{dataset} RMSE: {test_rmse}')
        print(f'{dataset} MAE: {test_mae}')
        print(f'{dataset} R2: {test_r2}')
        print('Regression slope:', slope)
        print('Regression intercept:', intercept)
        print(f'{dataset} rmselow: {rmselow}')
        print(f'{dataset} fabio: {fabio}')

    def save(self, model, model_filename: str) -> None:
        ''' 
        Save trained model

        :param model: trained model
        :param model_filename: path to save model as .pkl file
        '''
        # Save the trained model to a file using pickle
        with open(model_filename, 'wb') as file:
            pickle.dump(model, file)
        print(f'Trained model saved to {model_filename}')
