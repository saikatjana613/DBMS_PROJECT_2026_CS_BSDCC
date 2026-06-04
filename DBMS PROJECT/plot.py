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


# ============================================================
# 2. Architecture Diagram (simple block diagram)
# ============================================================
def plot_architecture():
    plt.figure(figsize=(10, 6))
    ax = plt.gca()
    ax.axis("off")

    boxes = {
        "User Input": (0.1, 0.6),
        "Query Parser": (0.35, 0.6),
        "Optimizer (Rules)": (0.6, 0.6),
        "Execution Engine": (0.85, 0.6),
        "SQLite DB": (0.6, 0.2),
    }

    for text, (x, y) in boxes.items():
        ax.text(x, y, text, ha="center", va="center",
                bbox=dict(boxstyle="round", facecolor="lightblue"))

    arrows = [
        ((0.15, 0.6), (0.30, 0.6)),
        ((0.40, 0.6), (0.55, 0.6)),
        ((0.65, 0.6), (0.80, 0.6)),
        ((0.60, 0.55), (0.60, 0.30)),
    ]

    for (x1, y1), (x2, y2) in arrows:
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="->", lw=2))

    plt.title("Overall System Architecture")
    plt.savefig("plots/architecture.png", dpi=300, bbox_inches="tight")
    plt.close()


# ============================================================
# 3. Modules Diagram
# ============================================================
def plot_modules():
    plt.figure(figsize=(10, 6))
    ax = plt.gca()
    ax.axis("off")

    modules = [
        "Schema Loader",
        "TPC-H Generator",
        "IMDB Generator",
        "DSB Generator",
        "Optimizer Engine",
        "Benchmark Runner"
    ]

    positions = [(0.2, 0.8), (0.5, 0.8), (0.8, 0.8),
                  (0.2, 0.4), (0.5, 0.4), (0.8, 0.4)]

    for m, (x, y) in zip(modules, positions):
        ax.text(x, y, m, ha="center", va="center",
                bbox=dict(boxstyle="round", facecolor="lightgreen"))

    plt.title("Software Modules Overview")
    plt.savefig("plots/modules.png", dpi=300, bbox_inches="tight")
    plt.close()


# ============================================================
# 4. Benchmark Comparison Plot
# ============================================================
def plot_benchmark_comparison():
    datasets = ["TPC-H", "IMDB/JOB", "DSB"]

    # Example performance metric (replace with actual execution time if you log it)
    execution_time = [120, 180, 150]  # in seconds

    plt.figure()
    plt.bar(datasets, execution_time)
    plt.title("Benchmark Performance Comparison")
    plt.xlabel("Dataset")
    plt.ylabel("Execution Time (seconds)")

    plt.savefig("plots/benchmark_comparison.png", dpi=300, bbox_inches="tight")
    plt.close()


# ============================================================
# MAIN
# ============================================================
if __name__ == "__main__":
    import os
    os.makedirs("plots", exist_ok=True)

    plot_dataset_distribution()
    plot_architecture()
    plot_modules()
    plot_benchmark_comparison()

    print("All plots generated successfully in /plots")