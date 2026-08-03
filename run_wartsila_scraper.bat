@echo off
cd /d "D:\Vessel_performance\Vessel_performance\Vessel_performance\Vessel_Performance"
call venv\Scripts\activate.bat
python -c "import sys; sys.path.append('D:/Vessel_performance/Vessel_performance/Vessel_performance/Vessel_Performance'); from backend.pipeline.wartsila_scraper import fetch_wartsila_routes; fetch_wartsila_routes()"
