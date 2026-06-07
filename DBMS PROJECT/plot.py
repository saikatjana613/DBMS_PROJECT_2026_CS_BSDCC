import matplotlib.pyplot as plt

# ============================================================
# 1. Dataset Distribution Plot
# ============================================================
def plot_dataset_distribution():
    datasets = ["TPC-H", "IMDB/JOB", "DSB"]

    # You can adjust these based on actual query counts in your system
    query_counts = [5, 3, 3]

    plt.figure()
    plt.bar(datasets, query_counts)
    plt.title("Distribution of Benchmark Queries Across Datasets")
    plt.xlabel("Dataset")
    plt.ylabel("Number of Queries")

    plt.savefig("plots/dataset_distribution.png", dpi=300, bbox_inches="tight")
    plt.close()

