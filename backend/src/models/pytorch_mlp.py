"""
backend/src/models/pytorch_mlp.py
==================================
GPU-accelerated PyTorch MLP Regressor.
Fully compatible with scikit-learn API for easy pickling and pipeline integration.
"""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
import numpy as np
from sklearn.base import BaseEstimator, RegressorMixin

class GPUMLPRegressorNet(nn.Module):
    """PyTorch Neural Network architecture matching sklearn hidden layers with regularization."""
    def __init__(self, input_dim, hidden_layer_sizes, dropout_rate=0.2):
        super().__init__()
        layers = []
        prev_dim = input_dim
        for size in hidden_layer_sizes:
            layers.append(nn.Linear(prev_dim, size))
            layers.append(nn.BatchNorm1d(size))
            layers.append(nn.ReLU())
            layers.append(nn.Dropout(dropout_rate))
            prev_dim = size
        layers.append(nn.Linear(prev_dim, 1))
        self.network = nn.Sequential(*layers)

    def forward(self, x):
        return self.network(x)

class PyTorchMLPRegressor(BaseEstimator, RegressorMixin):
    """Scikit-learn wrapper for PyTorch GPU-accelerated MLP Regressor."""
    def __init__(self, hidden_layer_sizes=(128, 64, 32), learning_rate=0.001, 
                 epochs=40, batch_size=4096, random_state=42, dropout_rate=0.2):
        self.hidden_layer_sizes = hidden_layer_sizes
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.random_state = random_state
        self.dropout_rate = dropout_rate
        self.model_ = None
        self.input_dim_ = None
        
        # Set seeds
        torch.manual_seed(self.random_state)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(self.random_state)

    def fit(self, X, y, eval_set=None):
        # Handle pandas dataframe
        if hasattr(X, "values"):
            X_arr = X.values
        else:
            X_arr = np.array(X)
            
        if hasattr(y, "values"):
            y_arr = y.values
        else:
            y_arr = np.array(y)
            
        self.input_dim_ = X_arr.shape[1]
        
        # Initialize network
        self.model_ = GPUMLPRegressorNet(self.input_dim_, self.hidden_layer_sizes, self.dropout_rate)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_.to(device)
        
        # Parse validation set for early stopping
        X_val_arr = None
        y_val_arr = None
        if eval_set is not None:
            val_data = eval_set[0] if isinstance(eval_set, list) else eval_set
            if val_data is not None and len(val_data) == 2:
                X_val_raw, y_val_raw = val_data
                X_val_arr = X_val_raw.values if hasattr(X_val_raw, "values") else np.array(X_val_raw)
                y_val_arr = y_val_raw.values if hasattr(y_val_raw, "values") else np.array(y_val_raw)

        # Prepare datasets
        X_tensor = torch.tensor(X_arr, dtype=torch.float32)
        y_tensor = torch.tensor(y_arr, dtype=torch.float32).unsqueeze(1)
        
        dataset = TensorDataset(X_tensor, y_tensor)
        loader = DataLoader(dataset, batch_size=self.batch_size, shuffle=True)
        
        criterion = nn.MSELoss()
        optimizer = optim.Adam(self.model_.parameters(), lr=self.learning_rate)
        
        # Setup early stopping
        patience = 5
        best_val_loss = float("inf")
        best_model_state = None
        patience_counter = 0
        
        X_val_tensor = None
        y_val_tensor = None
        if X_val_arr is not None and y_val_arr is not None:
            X_val_tensor = torch.tensor(X_val_arr, dtype=torch.float32).to(device)
            y_val_tensor = torch.tensor(y_val_arr, dtype=torch.float32).unsqueeze(1).to(device)

        print(f"[PyTorch MLP] Starting training on device: {device} for {self.epochs} epochs...")
        for epoch in range(1, self.epochs + 1):
            self.model_.train()
            epoch_loss = 0.0
            for batch_x, batch_y in loader:
                batch_x = batch_x.to(device)
                batch_y = batch_y.to(device)
                
                optimizer.zero_grad()
                predictions = self.model_(batch_x)
                loss = criterion(predictions, batch_y)
                loss.backward()
                optimizer.step()
                
                epoch_loss += loss.item() * batch_x.size(0)
            
            # Validation step
            val_loss_str = ""
            if X_val_tensor is not None and y_val_tensor is not None:
                self.model_.eval()
                with torch.no_grad():
                    val_preds = self.model_(X_val_tensor)
                    val_loss = criterion(val_preds, y_val_tensor).item()
                val_loss_str = f" | Validation Loss (MSE): {val_loss:.4f}"
                
                if val_loss < best_val_loss:
                    best_val_loss = val_loss
                    best_model_state = {k: v.cpu().clone() for k, v in self.model_.state_dict().items()}
                    patience_counter = 0
                else:
                    patience_counter += 1
            
            if epoch % 10 == 0 or epoch == 1:
                avg_loss = epoch_loss / len(X_tensor)
                print(f"  Epoch {epoch}/{self.epochs} - Training Loss (MSE): {avg_loss:.4f}{val_loss_str}")
                
            if X_val_tensor is not None and patience_counter >= patience:
                print(f"  [PyTorch MLP] Early stopping triggered at epoch {epoch}. Best validation MSE: {best_val_loss:.4f}")
                break
                
        if best_model_state is not None:
            self.model_.load_state_dict({k: v.to(device) for k, v in best_model_state.items()})
        self.model_.eval()
        return self

    def predict(self, X):
        if self.model_ is None:
            raise ValueError("This PyTorchMLPRegressor instance is not fitted yet.")
            
        if hasattr(X, "values"):
            X_arr = X.values
        else:
            X_arr = np.array(X)
            
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model_.to(device)
        self.model_.eval()
        
        X_tensor = torch.tensor(X_arr, dtype=torch.float32).to(device)
        with torch.no_grad():
            preds = self.model_(X_tensor).cpu().numpy().ravel()
            
        return preds

    def __getstate__(self):
        """Custom state handler for joblib. Saves weights to CPU to avoid CUDA serialization errors."""
        state = self.__dict__.copy()
        if 'model_' in state and state['model_'] is not None:
            # Save state dict of model mapped to CPU
            state['model_state_dict_'] = {k: v.cpu() for k, v in state['model_'].state_dict().items()}
            del state['model_']
        return state

    def __setstate__(self, state):
        """Custom reconstruction handler. Moves weights back to GPU if available."""
        self.__dict__.update(state)
        self.model_ = None
        if 'model_state_dict_' in state:
            input_dim = state.get('input_dim_', None)
            if input_dim:
                self.model_ = GPUMLPRegressorNet(input_dim, self.hidden_layer_sizes, getattr(self, "dropout_rate", 0.2))
                self.model_.load_state_dict(state['model_state_dict_'])
                device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
                self.model_.to(device)
                self.model_.eval()
