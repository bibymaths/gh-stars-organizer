"""Sensible cross-domain starting profiles; users can merge or replace them."""
from __future__ import annotations

PROFILES: dict[str, dict[str, list[str]]] = {
    "general": {
        "Programming Languages": ["programming language", "compiler", "interpreter", "language tooling"],
        "Frameworks and Libraries": ["framework", "library", "sdk", "package"],
        "Developer Tools": ["developer tools", "cli", "linter", "formatter", "debugger"],
        "Databases": ["database", "postgresql", "sqlite", "mongodb", "redis"],
        "Cloud and Infrastructure": ["kubernetes", "docker", "terraform", "infrastructure", "cloud"],
        "Web Development": ["web development", "frontend", "backend", "react", "fastapi"],
        "Mobile Development": ["mobile", "android", "ios", "flutter"],
        "Testing and Quality": ["testing", "pytest", "quality assurance", "unit test"],
        "Security": ["security", "cryptography", "vulnerability", "authentication"],
        "Documentation": ["documentation", "docs", "mkdocs", "sphinx"],
        "Learning Resources": ["tutorial", "course", "awesome list", "learning resources"],
    },
    "data": {
        "Data Engineering": ["data engineering", "etl", "data pipeline", "data warehouse"],
        "Statistics": ["statistics", "statistical inference", "regression"],
        "Machine Learning": ["machine learning", "scikit learn", "random forest"],
        "Deep Learning": ["deep learning", "neural network", "pytorch", "tensorflow"],
        "Data Visualization": ["data visualization", "plotly", "matplotlib", "dashboard"],
        "Scientific Computing": ["scientific computing", "numerical computing", "simulation"],
        "Data Processing": ["data processing", "dataframe", "pandas", "polars"],
        "AI Applications": ["ai application", "llm", "agent", "generative ai"],
        "Model Deployment": ["model serving", "mlops", "model deployment"],
        "Research Resources": ["research resources", "benchmark", "dataset", "paper collection"],
    },
    "scientific": {
        "Computational Biology": ["computational biology", "systems biology", "molecular modeling"],
        "Bioinformatics": ["bioinformatics", "genomics", "proteomics", "transcriptomics"],
        "Mathematical Optimization": ["optimization", "nonlinear programming", "global optimization"],
        "Numerical Methods": ["numerical methods", "numerical analysis", "numerical solver"],
        "Differential Equations": ["differential equation", "ode", "pde", "sde"],
        "Bayesian Inference": ["bayesian", "mcmc", "posterior inference"],
        "Network Science": ["network science", "graph algorithm", "graph theory"],
        "Scientific Machine Learning": ["scientific machine learning", "physics informed", "neural ode"],
        "High-Performance Computing": ["hpc", "parallel computing", "gpu computing"],
        "Scientific Visualization": ["scientific visualization", "visual analytics", "scientific plotting"],
        "Research Infrastructure": ["research workflow", "reproducibility", "workflow management"],
    },
    "minimal": {
        "Development": ["software", "development", "programming", "framework", "library"],
        "Data and Science": ["data", "science", "statistics", "research", "analysis"],
        "Infrastructure": ["infrastructure", "cloud", "devops", "container"],
        "Resources": ["documentation", "tutorial", "learning", "awesome list"],
    },
    "custom": {},
}

# Match aliases only as whole, normalized phrases; short acronyms never substring-match.
ALIASES: dict[str, list[str]] = {
    "differential equation": ["differential equations"],
    "neural network": ["neural networks"],
    "graph algorithm": ["graph algorithms"],
    "numerical method": ["numerical methods"],
    "data pipeline": ["data pipelines"],
    "scikit learn": ["scikit-learn"],
}
