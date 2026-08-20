import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

def visualize():
    if not os.path.exists("rr_optimization_results.csv"):
        print("CSV not found.")
        return

    df = pd.read_csv("rr_optimization_results.csv")
    
    # Processar dados para gráfico
    summary = []
    for rr in ["1:3", "1:4", "1:5"]:
        for stype in ["Support", "Breakout"]:
            subset = df[(df['rr_ratio'] == rr) & (df['type'] == stype)]
            wins = len(subset[subset['status'] == 'WIN'])
            losses = len(subset[subset['status'] == 'LOSS'])
            wr = (wins / (wins + losses)) * 100 if (wins + losses) > 0 else 0
            profit = subset['profit'].sum()
            summary.append({'RR': rr, 'Strategy': stype, 'WinRate': wr, 'Profit': profit})
    
    plot_df = pd.DataFrame(summary)

    plt.figure(figsize=(12, 6))
    
    # Gráfico de Lucro
    plt.subplot(1, 2, 1)
    sns.barplot(data=plot_df, x='RR', y='Profit', hue='Strategy')
    plt.title('Lucro Acumulado (R) por Rácio RR')
    plt.ylabel('Lucro (Unidades de Risco)')
    plt.grid(axis='y', linestyle='--', alpha=0.7)

    # Gráfico de Win Rate
    plt.subplot(1, 2, 2)
    sns.barplot(data=plot_df, x='RR', y='WinRate', hue='Strategy')
    plt.title('Taxa de Acerto (%) por Rácio RR')
    plt.ylabel('Win Rate (%)')
    plt.grid(axis='y', linestyle='--', alpha=0.7)

    plt.tight_layout()
    plt.savefig('rr_optimization_chart.png')
    print("Gráfico guardado como rr_optimization_chart.png")

if __name__ == "__main__":
    visualize()
