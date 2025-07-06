import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
from typing import List, Dict, Optional
from collections import defaultdict
class KworbScraper:
    def __init__(self):
        self.base_url = "https://kworb.net/spotify/country/global_daily_totals.html"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    def get_page_content(self) -> Optional[BeautifulSoup]:
        """Obtiene el contenido HTML de la página"""
        try:
            response = requests.get(self.base_url, headers=self.headers)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.RequestException as e:
            print(f"Error al obtener la página: {e}")
            return None
    

    def scrape_data(self) -> List[Dict]:
        """Extrae todos los datos de la tabla"""
        soup = self.get_page_content()
        if not soup:
            return []

        table = soup.find('table')
        
        if not table:
            print("No se encontró tabla en la página")
            return []
        
        data = []

        header_row = table.find('tr')
        headers = []
        if header_row:
            for th in header_row.find_all(['th', 'td']):
                header_text = th.get_text(strip=True)
                if header_text:
                    headers.append(header_text)
        
        print(f"Headers encontrados: {headers}")
        
        rows = table.find_all('tr')
        print(f"Procesando {len(rows)} filas...")
        
        for i, row in enumerate(rows):
            if i == 0:
                continue
                
            cells = row.find_all(['td', 'th'])
            if not cells:
                continue

            row_data = {}
            for j, cell in enumerate(cells):
                cell_text = cell.get_text(strip=True)
                if j < len(headers):
                    column_name = headers[j]
                else:
                    column_name = f"columna_{j+1}"
                row_data[column_name] = cell_text
            
            if row_data:  
                data.append(row_data)
            
        print(f"Scraping completado. Total de canciones: {len(data)}")
        return data
    
    def save_to_csv(self, data: List[Dict], filename: str = "kworb_spotify_data.csv"):
        """Guarda los datos en un archivo CSV"""
        if not data:
            print("No hay datos para guardar")
            return
        
        df = pd.DataFrame(data)
        df.to_csv(filename, index=False, encoding='utf-8')
        print(f"Datos guardados en {filename}")

        print(f"\nEstadísticas básicas:")
        print(f"Total de canciones: {len(df)}")

        print(f"\nColumnas extraídas: {list(df.columns)}")
        
        return df

def main():
    """Función principal"""
    print("Iniciando scraping de Kworb Spotify Global Daily Totals...")
    
    scraper = KworbScraper()
    
    data = scraper.scrape_data()
    
    if data:
        df = scraper.save_to_csv(data, "data/kworb_spotify_global_totals.csv")
        
        print("\nPrimeras 5 canciones:")
        print(df.head().to_string())

        if 'total_streams' in df.columns and df['total_streams'].notna().any():
            print("\nTop 10 canciones por streams totales:")
            top_songs = df.nlargest(10, 'total_streams')[['artist_song', 'total_streams']]
            print(top_songs.to_string())
        
    else:
        print("No se pudieron obtener datos")

if __name__ == "__main__":
    main()