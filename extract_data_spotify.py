#!/usr/bin/env python3

import pandas as pd
import json
import requests
import base64
import time
import os
import concurrent.futures
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
CACHE_FILE = "conflict_data_from_spotify.json"
OUTPUT_FILE = "conflict_data_from_spotify.json"
MAX_WORKERS = 3 
MAX_RETRIES = 3  

class SpotifyAPI:
    def __init__(self):
        self.access_token = None
        self.token_expiry = None
        self.cache = self._load_cache()
        self._validate_credentials()
        self.rate_limit_queue = [] 
        self.last_request_time = 0
    
    def _validate_credentials(self):
        if not CLIENT_ID or not CLIENT_SECRET:
            raise ValueError("❌ CLIENT_ID o CLIENT_SECRET no están configurados en el archivo .env")
        if CLIENT_ID == "tu_client_id" or CLIENT_SECRET == "tu_client_secret":
            raise ValueError("❌ Actualiza CLIENT_ID y CLIENT_SECRET en el archivo .env con tus credenciales reales de Spotify")
        print(f"✅ Credenciales cargadas: CLIENT_ID={CLIENT_ID[:8]}...{CLIENT_ID[-4:]}")
    
    def _load_cache(self):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def _save_cache(self):
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=4, ensure_ascii=False)
    
    def _get_new_token(self):
        print(f"🔐 Solicitando token con CLIENT_ID: {CLIENT_ID[:8]}...{CLIENT_ID[-4:]}")
        
        auth_string = f"{CLIENT_ID}:{CLIENT_SECRET}"
        auth_bytes = auth_string.encode('utf-8')
        auth_base64 = str(base64.b64encode(auth_bytes), 'utf-8')

        auth_url = 'https://accounts.spotify.com/api/token'
        headers = {
            'Authorization': f'Basic {auth_base64}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        data = {'grant_type': 'client_credentials'}

        print(f"Enviando solicitud de autenticación a: {auth_url}")
        response = requests.post(auth_url, headers=headers, data=data)
        
        print(f"Respuesta del servidor: {response.status_code}")
        
        if response.status_code != 200:
            print(f"Detalles del error: {response.text}")
           
            raise Exception(f"Auth failed: {response.status_code} - {response.text}")
        
        token_data = response.json()
        self.access_token = token_data['access_token']
        self.token_expiry = time.time() + token_data.get('expires_in', 3600)
        print(f"✅ Token obtenido exitosamente, expira en {token_data.get('expires_in', 3600)} segundos")
        return self.access_token
    
    def get_token(self):
        if not self.access_token or time.time() > self.token_expiry:
            print("Obtaining new access token...")
            return self._get_new_token()
        return self.access_token
    
    def _rate_limit_delay(self):
        """Controla el rate limiting entre llamadas"""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < 0.1:  
            time.sleep(0.1 - elapsed)
        self.last_request_time = time.time()
    
    def _process_track_data(self, track_id, attempt=0):
        """Función interna para procesar datos de un track"""
        try:
            self._rate_limit_delay()
            access_token = self.get_token()
            
            track_url = f'https://api.spotify.com/v1/tracks/{track_id}'
            headers = {'Authorization': f'Bearer {access_token}'}
            
            track_response = requests.get(track_url, headers=headers)
            
            if track_response.status_code == 401:
                print(f"🔄 Token expirado para {track_id}, renovando...")
                self.access_token = None
                return None
            elif track_response.status_code == 403:
                print(f"🚫 Error 403 para {track_id}: {track_response.text}")
                return None
            elif track_response.status_code == 429:
                retry_after = int(track_response.headers.get('Retry-After', 5))
                print(f"⏳ Rate limit alcanzado, reintentando {track_id} después de {retry_after} segundos...")
                time.sleep(retry_after)
                return None
            elif track_response.status_code != 200:
                print(f"⚠️ Error getting track {track_id}: {track_response.status_code} - {track_response.text}")
                return None
                
            track_data = track_response.json()
            
            features_url = f'https://api.spotify.com/v1/audio-features/{track_id}'
            features_response = requests.get(features_url, headers=headers)
            audio_features = features_response.json() if features_response.status_code == 200 else {}
 
            audio_analysis = {}
            try:
                analysis_url = f'https://api.spotify.com/v1/audio-analysis/{track_id}'
                analysis_response = requests.get(analysis_url, headers=headers)
                if analysis_response.status_code == 200:
                    analysis_data = analysis_response.json()
                    audio_analysis = {
                        'sections': analysis_data.get('sections', [])[:3],
                        'segments': analysis_data.get('segments', [])[:3],
                        'beats': analysis_data.get('beats', [])[:5],
                        'bars': analysis_data.get('bars', [])[:5]
                    }
            except Exception as e:
                print(f"⚠️ Audio analysis failed for {track_id}: {str(e)}")
            

            album_data = {}
            if 'album' in track_data and 'id' in track_data['album']:
                try:
                    album_url = f'https://api.spotify.com/v1/albums/{track_data["album"]["id"]}'
                    album_response = requests.get(album_url, headers=headers)
                    if album_response.status_code == 200:
                        album_data = {
                            'label': album_response.json().get('label'),
                            'copyrights': album_response.json().get('copyrights'),
                            'total_tracks': album_response.json().get('total_tracks')
                        }
                except Exception as e:
                    print(f"⚠️ Album data failed for {track_id}: {str(e)}")
            
            artist_data = {}
            if 'artists' in track_data and len(track_data['artists']) > 0:
                try:
                    artist_id = track_data['artists'][0]['id']
                    artist_url = f'https://api.spotify.com/v1/artists/{artist_id}'
                    artist_response = requests.get(artist_url, headers=headers)
                    if artist_response.status_code == 200:
                        artist_data = {
                            'genres': artist_response.json().get('genres', []),
                            'popularity': artist_response.json().get('popularity')
                        }
                except Exception as e:
                    print(f"⚠️ Artist data failed for {track_id}: {str(e)}")
            
            complete_data = {
                'track_id': track_id,
                'track_metadata': track_data,
                'audio_features': audio_features,
                'audio_analysis': audio_analysis,
                'album_details': album_data,
                'artist_details': artist_data,
                'api_fetch_timestamp': datetime.now().isoformat()
            }
            
            self.cache[track_id] = complete_data
            self._save_cache()
            
            return complete_data
            
        except Exception as e:
            print(f"❌ Error processing track {track_id} (attempt {attempt}): {str(e)}")
            return None
    
    def get_track_data(self, track_id):
        if track_id in self.cache:
            print(f"📦 Using cached data for {track_id}")
            return self.cache[track_id]
        
        print(f"🌐 Fetching fresh data for {track_id}")
        
        for attempt in range(MAX_RETRIES):
            result = self._process_track_data(track_id, attempt)
            if result is not None:
                return result
            
            if attempt < MAX_RETRIES - 1:
                wait_time = 2 ** attempt  
                print(f"🔄 Reintentando {track_id} en {wait_time} segundos...")
                time.sleep(wait_time)
        
        print(f"❌ Todos los intentos fallaron para {track_id}")
        return None

def process_track(spotify, track_id):
    """Función para procesar un track individual (usada en threads)"""
    try:
        return spotify.get_track_data(track_id)
    except Exception as e:
        print(f"❌ Error inesperado procesando {track_id}: {str(e)}")
        return None

def save_progress_backup(all_spotify_data, cached_count, fresh_count, failed_count, track_ids, genre_distribution, progress_label):
    """Guarda un backup del progreso actual"""
    backup_filename = f"spotify_data_backup_{progress_label.replace('%', 'percent')}.json"
    
    output_data = {
        'metadata': {
            'extraction_date': datetime.now().isoformat(),
            'source_file': 'predict-the-success-of-songs-on-digital-platforms/data/merge_spotify.csv',
            'description': f'Backup de datos de Spotify API - {progress_label} completado',
            'total_records': len(all_spotify_data),
            'cached_data_used': cached_count,
            'fresh_data_fetched': fresh_count,
            'failed_requests': failed_count,
            'filter_criteria': 'is_conflict == True OR is_conflict == null',
            'genre_distribution': dict(genre_distribution),
            'unique_track_ids_processed': len(track_ids),
            'concurrent_workers': MAX_WORKERS,
            'progress_status': progress_label
        },
        'spotify_data': all_spotify_data
    }
    
    try:
        with open(backup_filename, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        file_size_mb = os.path.getsize(backup_filename) / (1024 * 1024)
        print(f"💾 ✅ Backup guardado: {backup_filename} ({file_size_mb:.1f} MB)")
        print(f"📊 Registros en backup: {len(all_spotify_data)}")
        
    except Exception as e:
        print(f"❌ Error al guardar backup {progress_label}: {str(e)}")

def extract_conflict_data():
    print("🚀 EXTRACTOR DE DATOS DESDE SPOTIFY API")
    print("=" * 60)

    spotify = SpotifyAPI()
    
    print("🔍 Cargando dataset merge_spotify.csv...")
    
    try:
        df = pd.read_csv('data/spotify-tracks.csv', 
                        index_col=0, low_memory=False)
        print(f"✅ Dataset cargado: {len(df)} filas")
    except Exception as e:
        print(f"❌ Error al cargar el dataset: {str(e)}")
        return

    track_ids = df['track_id'].unique()
    print(f"\n🎵 IDs únicos de Spotify a procesar: {len(track_ids)}")
    
    print(f"\n🎵 Distribución por género de las filas con conflictos:")
    genre_distribution = df['track_genre'].value_counts()
    for genre, count in genre_distribution.items():
        print(f"   - {genre}: {count} canciones")
    
    print(f"\n🚀 Procesando {len(track_ids)} canciones con {MAX_WORKERS} workers...")
    
    all_spotify_data = []
    cached_count = 0
    fresh_count = 0
    failed_count = 0
    
    tracks_to_fetch = []
    for track_id in track_ids:
        if track_id in spotify.cache:
            cached_count += 1
            all_spotify_data.append(spotify.cache[track_id])
        else:
            tracks_to_fetch.append(track_id)
    
    print(f"   - {cached_count} tracks obtenidos de caché")
    print(f"   - {len(tracks_to_fetch)} tracks a obtener de la API")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = []
        for track_id in tracks_to_fetch:
            futures.append(executor.submit(process_track, spotify, track_id))
        
        total_to_process = len(tracks_to_fetch)
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            result = future.result()
            if result:
                fresh_count += 1
                all_spotify_data.append(result)
            else:
                failed_count += 1
            
            progress_percent = ((i + 1) / total_to_process) * 100
            
            if 49.5 <= progress_percent < 50.5 and not hasattr(extract_conflict_data, '_saved_50'):
                print(f"🎯 50% COMPLETADO - Guardando backup...")
                save_progress_backup(all_spotify_data, cached_count, fresh_count, failed_count, 
                                   track_ids, genre_distribution, "50%")
                extract_conflict_data._saved_50 = True
            
            if (i + 1) % 10 == 0:
                print(f"📊 Progreso: {i + 1}/{total_to_process} ({progress_percent:.1f}%) | Exitosos: {fresh_count + cached_count} | Fallidos: {failed_count}")
    
    print(f"\n📊 Resultados del procesamiento:")
    print(f"   ✅ Exitosos: {len(all_spotify_data)}")
    print(f"     - De caché: {cached_count}")
    print(f"     - Nuevos: {fresh_count}")
    print(f"   ❌ Fallidos: {failed_count}")
    print(f"   📈 Tasa de éxito: {(len(all_spotify_data)/len(track_ids))*100:.1f}%")
    
    print(f"\n🎯 100% COMPLETADO - Guardando backup final...")
    save_progress_backup(all_spotify_data, cached_count, fresh_count, failed_count, 
                        track_ids, genre_distribution, "100%")
    
    output_data = {
        'metadata': {
            'extraction_date': datetime.now().isoformat(),
            'source_file': 'predict-the-success-of-songs-on-digital-platforms/data/merge_spotify.csv',
            'description': 'Datos completos de Spotify API para filas con is_conflict = True o null',
            'total_records': len(all_spotify_data),
            'cached_data_used': cached_count,
            'fresh_data_fetched': fresh_count,
            'failed_requests': failed_count,
            'filter_criteria': 'is_conflict == True OR is_conflict == null',
            'genre_distribution': dict(genre_distribution),
            'unique_track_ids_processed': len(track_ids),
            'concurrent_workers': MAX_WORKERS
        },
        'spotify_data': all_spotify_data
    }
    
    print(f"\n💾 Guardando datos en {OUTPUT_FILE}...")
    
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        print(f"✅ Datos guardados exitosamente en {OUTPUT_FILE}")
        print(f"📁 Archivo creado con {len(all_spotify_data)} registros completos de Spotify")
        
        
    except Exception as e:
        print(f"❌ Error al guardar el archivo JSON: {str(e)}")

if __name__ == '__main__':
    extract_conflict_data()
    print("\n🎯 EXTRACCIÓN COMPLETADA!")