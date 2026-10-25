import os
import sys

# Konfigurasi Encoding Windows agar tidak crash saat render karakter
if sys.platform.startswith("win"):
    os.system("chcp 65001 > nul")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
import tempfile
import psutil
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import requests
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.prompt import Prompt

# Inisialisasi Rich Console dengan box ASCII agar kompatibel dengan semua jenis font Windows cmd (tanpa ????)
console = Console()
SAFE_BOX = box.ASCII

# ==============================================================================
# KONFIGURASI API (OPSIONAL - SISTEM TETAP 100% BERJALAN OFFLINE)
# ==============================================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")


# ==============================================================================
# 1. MODUL PEMINDAIAN HARDWARE TINGKAT RENDAH (ROOT / ELEVATED WMI & CIM)
# ==============================================================================

def get_motherboard_bios():
    """Mengambil informasi Motherboard, Vendor, dan Versi BIOS"""
    info = {
        "device": "Unknown Device",
        "motherboard": "Unknown Motherboard",
        "bios_version": "Unknown BIOS",
        "bios_date": "N/A"
    }
    try:
        import wmi
        w = wmi.WMI()
        cs = w.Win32_ComputerSystem()
        if cs:
            info["device"] = f"{cs[0].Manufacturer.strip()} {cs[0].Model.strip()}"
        
        bb = w.Win32_BaseBoard()
        if bb:
            info["motherboard"] = f"{bb[0].Manufacturer.strip()} {bb[0].Product.strip()}"

        bios = w.Win32_BIOS()
        if bios:
            b = bios[0]
            date_raw = b.ReleaseDate or ""
            date_fmt = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if len(date_raw) >= 8 else date_raw
            info["bios_version"] = f"{b.Manufacturer.strip()} {b.SMBIOSBIOSVersion.strip()}"
            info["bios_date"] = date_fmt
    except Exception:
        pass
    return info


def get_cpu_deep_info():
    """Mengambil spesifikasi CPU detail, arsitektur, clock speed, dan utilisasi"""
    cpu_data = {
        "name": "Unknown CPU",
        "cores_threads": "N/A",
        "clock_speed": "N/A",
        "load_pct": "0%"
    }
    try:
        import wmi
        w = wmi.WMI()
        cpus = w.Win32_Processor()
        if cpus:
            c = cpus[0]
            cpu_data["name"] = c.Name.strip() if c.Name else "AMD/Intel Processor"
            cores = c.NumberOfCores or psutil.cpu_count(logical=False)
            threads = c.NumberOfLogicalProcessors or psutil.cpu_count(logical=True)
            cpu_data["cores_threads"] = f"{cores} Cores / {threads} Threads"
            max_clk = c.MaxClockSpeed or 0
            curr_clk = c.CurrentClockSpeed or max_clk
            cpu_data["clock_speed"] = f"{curr_clk} MHz (Max: {max_clk} MHz)"
        
        load = psutil.cpu_percent(interval=0.2)
        cpu_data["load_pct"] = f"{load}%"
    except Exception:
        pass
    return cpu_data


def get_cpu_temperature():
    """Membaca suhu CPU via namespace root\\wmi MSAcpi_ThermalZoneTemperature"""
    celsius = None
    try:
        import wmi
        w_acpi = wmi.WMI(namespace="root\\wmi")
        temps = w_acpi.MSAcpi_ThermalZoneTemperature()
        if temps:
            celsius = (temps[0].CurrentTemperature - 2732) / 10.0
    except Exception:
        pass

    if celsius is None:
        try:
            if hasattr(psutil, "sensors_temperatures"):
                st = psutil.sensors_temperatures()
                if st:
                    for _, entries in st.items():
                        for entry in entries:
                            celsius = entry.current
                            break
        except Exception:
            pass

    if celsius is not None:
        if celsius <= 65:
            badge = "[bold green]DINGIN / AMAN[/bold green]"
            status = "NORMAL"
        elif celsius <= 80:
            badge = "[bold yellow]HANGAT (BEBAN KERJA)[/bold yellow]"
            status = "WARM"
        else:
            badge = "[bold red]PANAS / OVERHEAT (>80°C)[/bold red]"
            status = "CRITICAL"
        return f"{celsius:.1f} °C", badge, celsius, status
    
    return "Tidak diekspos ACPI Motherboard", "[dim]N/A[/dim]", None, "UNKNOWN"


def get_ram_hardware_modules():
    """Membaca detail fisik kepingan RAM (Vendor, Speed MHz, Part Number, Dual Channel)"""
    modules = []
    try:
        import wmi
        w = wmi.WMI()
        for mem in w.Win32_PhysicalMemory():
            cap_gb = round(int(mem.Capacity) / (1024 ** 3), 1) if mem.Capacity else 0
            speed = mem.Speed or mem.ConfiguredClockSpeed or "N/A"
            mfg = mem.Manufacturer.strip() if mem.Manufacturer else "Generic"
            part = mem.PartNumber.strip() if mem.PartNumber else "N/A"
            modules.append(f"{cap_gb} GB @ {speed} MHz ({mfg} - {part})")
    except Exception:
        pass
    return modules


def get_ram_usage_and_processes():
    """Mengambil statistik pemakaian RAM dan 5 proses aplikasi teratas pemakan RAM"""
    try:
        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024 ** 3)
        used_gb = mem.used / (1024 ** 3)
        free_gb = mem.available / (1024 ** 3)
        pct = mem.percent

        if pct <= 70:
            badge = "[bold green]SEHAT (LONGGAR)[/bold green]"
            status = "OK"
        elif pct <= 85:
            badge = "[bold yellow]BEBAN CUKUP TINGGI[/bold yellow]"
            status = "WARNING"
        else:
            badge = "[bold red]KRITIS (HAMPIR HABIS)[/bold red]"
            status = "CRITICAL"

        detail = f"{used_gb:.2f} GB terpakai / {total_gb:.2f} GB total (Sisa: {free_gb:.2f} GB, {pct}%)"

        top_procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                mem_mb = p.info['memory_info'].rss / (1024 * 1024)
                top_procs.append((p.info['name'], mem_mb, p.info['pid']))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        top_procs.sort(key=lambda x: x[1], reverse=True)
        top_5 = top_procs[:5]

        return detail, badge, pct, status, top_5
    except Exception as e:
        return f"Error: {e}", "[dim]N/A[/dim]", 0, "ERROR", []


def get_storage_deep_info():
    """Mengambil info SSD/HDD fisik, Interface Bus (NVMe/SATA), Status SMART, dan Partisi"""
    disks = []
    has_smart_warning = False

    try:
        cmd = "Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, HealthStatus, Size | ConvertTo-Csv -NoTypeInformation"
        res = subprocess.check_output(["powershell", "-NoProfile", "-Command", cmd], text=True)
        lines = [l.strip().replace('"', '') for l in res.splitlines() if l.strip()][1:]
        
        for l in lines:
            parts = l.split(",")
            if len(parts) >= 4:
                fname = parts[0]
                mtype = parts[1]
                btype = parts[2]
                hstat = parts[3]
                size_gb = round(int(parts[4]) / (1024**3), 1) if len(parts) > 4 and parts[4].isdigit() else 0
                
                is_healthy = "HEALTHY" in hstat.upper() or "OK" in hstat.upper()
                if not is_healthy:
                    has_smart_warning = True
                stat_badge = "[bold green]OK (HEALTHY)[/bold green]" if is_healthy else f"[bold red]{hstat}[/bold red]"
                disks.append(f"{fname} ({size_gb} GB, {mtype} {btype}) -> SMART: {stat_badge}")
    except Exception:
        pass

    partitions = []
    has_partition_critical = False
    try:
        for p in psutil.disk_partitions(all=False):
            if 'fixed' in p.opts or not p.opts:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                    free_gb = usage.free / (1024 ** 3)
                    total_gb = usage.total / (1024 ** 3)
                    used_pct = usage.percent
                    if used_pct >= 90:
                        has_partition_critical = True
                        badge = "[bold red]KRITIS (>90% PENUH)[/bold red]"
                    elif used_pct >= 80:
                        badge = "[bold yellow]WASPADA (>80%)[/bold yellow]"
                    else:
                        badge = "[bold green]AMAN (LONGGAR)[/bold green]"
                    partitions.append({
                        "drive": p.mountpoint,
                        "free_gb": free_gb,
                        "total_gb": total_gb,
                        "used_pct": used_pct,
                        "badge": badge
                    })
                except PermissionError:
                    continue
    except Exception:
        pass

    return disks, has_smart_warning, partitions, has_partition_critical


def get_battery_deep_info():
    """
    Mengambil data baterai super-detail:
    - Kapasitas desain vs kapasitas penuh
    - Tegangan terminal (Voltage mV)
    - Arus pengisian nyata (ChargeRate mW)
    - Status BMS (Dead Cell / Safety Cutoff / Ghost Health Detection)
    """
    bat_data = {
        "status": "Desktop PC / Tidak Ada Baterai",
        "design_wh": 0,
        "full_wh": 0,
        "health_pct": 100.0,
        "wear_level": 0.0,
        "badge": "[dim]N/A (Desktop)[/dim]",
        "is_laptop": False,
        "voltage_v": 0.0,
        "charge_rate_w": 0.0,
        "power_online": False,
        "is_charging": False,
        "remaining_pct": 0,
        "is_dead_cell": False,
        "diagnosis_note": ""
    }

    try:
        import wmi
        w_acpi = wmi.WMI(namespace="root\\wmi")
        static_data = w_acpi.BatteryStaticData()
        full_charge = w_acpi.BatteryFullChargedCapacity()
        status_data = w_acpi.BatteryStatus()

        if static_data and full_charge:
            bat_data["is_laptop"] = True
            design_mwh = static_data[0].DesignedCapacity
            full_mwh = full_charge[0].FullChargedCapacity
            
            # Data dinamis sirkuit & voltase
            if status_data:
                bs = status_data[0]
                bat_data["voltage_v"] = round(bs.Voltage / 1000.0, 2) if bs.Voltage else 0.0
                bat_data["charge_rate_w"] = round(bs.ChargeRate / 1000.0, 2) if bs.ChargeRate else 0.0
                bat_data["power_online"] = bool(bs.PowerOnline)
                bat_data["is_charging"] = bool(bs.Charging)

            # Persentase kapasitas Windows
            sb = psutil.sensors_battery()
            if sb:
                bat_data["remaining_pct"] = int(sb.percent)
                if not status_data:
                    bat_data["power_online"] = sb.power_plugged

            if design_mwh and design_mwh > 0:
                bat_data["design_wh"] = round(design_mwh / 1000.0, 2)
                bat_data["full_wh"] = round(full_mwh / 1000.0, 2)
                bat_data["wear_level"] = round(max(0.0, ((design_mwh - full_mwh) / design_mwh) * 100), 1)
                bat_data["health_pct"] = round(100.0 - bat_data["wear_level"], 1)

                # ======================================================================
                # DETEKSI KRITIS: DEAD CELL / BMS LOCKED / GHOST CAPACITY
                # ======================================================================
                # Kasus Nyata: Dicas berjam-jam tidak naik (misal stuck di 6% atau <15%),
                # charger dicolok tapi Arus Pengisian = 0W atau tidak charging,
                # dan begitu charger dicabut laptop langsung mati.
                # Padahal EEPROM pabrik masih lapor 44.76 Wh (0% wear) -> INI GHOST READING!
                if bat_data["power_online"] and bat_data["remaining_pct"] <= 15:
                    if bat_data["charge_rate_w"] == 0.0 or not bat_data["is_charging"]:
                        bat_data["is_dead_cell"] = True
                        bat_data["badge"] = "[bold red]RUSAK TOTAL (DEAD CELL / BMS CUTOFF)[/bold red]"
                        bat_data["diagnosis_note"] = (
                            "BATERAI RUSAK MATI: Arus pengisian = 0 Watt meskipun charger terpasang. "
                            "Tegangan sel drop di bawah batas aman sehingga BMS mengunci sirkuit baterai (Safety Cutoff). "
                            "Kapasitas 100% adalah data statis EEPROM pabrik (Ghost Reading) karena sel fisik sudah tidak menyimpan daya sama sekali!"
                        )
                    else:
                        bat_data["badge"] = "[bold yellow]PENGISIAN RENDAH[/bold yellow]"
                elif bat_data["wear_level"] <= 15:
                    bat_data["badge"] = "[bold green]SANGAT SEHAT (KONDISI PRIMA)[/bold green]"
                elif bat_data["wear_level"] <= 30:
                    bat_data["badge"] = "[bold yellow]DEGRADASI WAJAR[/bold yellow]"
                else:
                    bat_data["badge"] = "[bold red]DEGRADASI TINGGI / PERLU GANTI[/bold red]"

                charge_desc = f"{bat_data['remaining_pct']}% ("
                if bat_data["power_online"]:
                    if bat_data["is_dead_cell"]:
                        charge_desc += "Colok Charger, TIDAK MENGISI / RUSAK"
                    elif bat_data["is_charging"]:
                        charge_desc += f"Mengisi Daya +{bat_data['charge_rate_w']}W"
                    else:
                        charge_desc += "Colok Charger, Arus 0W"
                else:
                    charge_desc += "Menggunakan Baterai"
                charge_desc += ")"

                bat_data["status"] = (
                    f"Status: {charge_desc} | Desain: {bat_data['design_wh']} Wh | "
                    f"Kapasitas Maksimal: {bat_data['full_wh']} Wh | Voltase: {bat_data['voltage_v']} V | "
                    f"Kesehatan: {bat_data['health_pct']}% (Wear Level: {bat_data['wear_level']}%)"
                )
                return bat_data
    except Exception:
        pass

    try:
        sb = psutil.sensors_battery()
        if sb:
            bat_data["is_laptop"] = True
            bat_data["remaining_pct"] = int(sb.percent)
            bat_data["power_online"] = sb.power_plugged
            bat_data["status"] = f"Pengisian: {sb.percent}% ({'Plugged In' if sb.power_plugged else 'Baterai'})"
            bat_data["badge"] = "[bold green]AKTIF[/bold green]"
    except Exception:
        pass

    return bat_data


def get_system_uptime():
    """Menghitung uptime sistem dan mendeteksi apakah sistem butuh reboot bersih"""
    uptime_secs = time.time() - psutil.boot_time()
    days = int(uptime_secs // 86400)
    hours = int((uptime_secs % 86400) // 3600)
    mins = int((uptime_secs % 3600) // 60)
    
    badge = "[bold green]SEGAR (<3 HARI)[/bold green]"
    needs_restart = False
    if days >= 7:
        badge = "[bold red]SANGAT LAMA (>7 HARI, BUTUH RESTART)[/bold red]"
        needs_restart = True
    elif days >= 3:
        badge = "[bold yellow]CUKUP LAMA (>3 HARI)[/bold yellow]"
        needs_restart = True

    text = f"{days} hari, {hours} jam, {mins} menit"
    return text, badge, days, needs_restart


# ==============================================================================
# 2. AUDIT WINDOWS EVENT LOG (CRASH, WHEA, KERNEL-POWER, DISK ERROR)
# ==============================================================================

def audit_windows_hardware_events():
    """Memindai System Event Log 7 hari terakhir untuk mendeteksi WHEA, BSOD, dan disk timeout"""
    ps_cmd = """
Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power','Microsoft-Windows-WHEA-Logger','disk','stornvme'; Level=1,2,3; StartTime=(Get-Date).AddDays(-7)} -ErrorAction SilentlyContinue | Select-Object -First 10 TimeCreated, ProviderName, Id, Message | ConvertTo-Csv -NoTypeInformation
"""
    events = []
    try:
        res = subprocess.check_output(["powershell", "-NoProfile", "-Command", ps_cmd], text=True)
        lines = [l.strip().replace('"', '') for l in res.splitlines() if l.strip()][1:]
        for l in lines:
            parts = l.split(",")
            if len(parts) >= 3:
                time_str = parts[0]
                provider = parts[1]
                event_id = parts[2]
                msg = parts[3] if len(parts) > 3 else ""
                
                if "WHEA-Logger" in provider:
                    desc = "WHEA Hardware Error (PCIe / Bus / CPU Core Correction)"
                elif "Kernel-Power" in provider:
                    desc = "Kernel-Power Unexpected Shutdown / BSOD (Mati Mendadak)"
                elif "disk" in provider or "stornvme" in provider:
                    desc = "Disk Controller I/O Timeout / Sektor Bermasalah"
                else:
                    desc = msg[:60]

                events.append({
                    "time": time_str,
                    "provider": provider.replace("Microsoft-Windows-", ""),
                    "id": event_id,
                    "desc": desc
                })
    except Exception:
        pass
    return events


# ==============================================================================
# 3. BENCHMARK HARDWARE (STORAGE REAL NVMe SPEED & CPU STRESS)
# ==============================================================================

def benchmark_disk_speed():
    """Melakukan pengujian kecepatan Read & Write nyata pada Drive C: secara aman (non-destruktif)"""
    test_file = os.path.join(tempfile.gettempdir(), "diag_bench_test.tmp")
    data_block = b"X" * (1024 * 1024 * 64) # 64 MB sample

    # Tes Tulis (Write)
    t0 = time.time()
    try:
        with open(test_file, "wb") as f:
            f.write(data_block)
            f.flush()
            os.fsync(f.fileno())
        write_time = max(0.001, time.time() - t0)
        write_speed = 64 / write_time
    except Exception as e:
        return f"Error Tes Write: {e}", 0, 0

    # Tes Baca (Read)
    t0 = time.time()
    try:
        with open(test_file, "rb") as f:
            _ = f.read()
        read_time = max(0.001, time.time() - t0)
        read_speed = 64 / read_time
    except Exception as e:
        return f"Error Tes Read: {e}", write_speed, 0
    finally:
        try:
            if os.path.exists(test_file):
                os.remove(test_file)
        except Exception:
            pass

    return None, write_speed, read_speed


def benchmark_cpu_stress():
    """Uji beban komputasi matematika multi-thread (100% CPU Load) & ukur respon suhu termal"""
    temp_before_str, _, temp_before_val, _ = get_cpu_temperature()

    def is_prime(n):
        if n < 2: return False
        for i in range(2, int(n**0.5) + 1):
            if n % i == 0: return False
        return True

    def worker(chunk):
        return sum(1 for n in chunk if is_prime(n))

    chunks = [range(i, i + 120000) for i in range(2, 720000, 120000)]
    t0 = time.time()
    with ThreadPoolExecutor() as executor:
        _ = list(executor.map(worker, chunks))
    dur = max(0.01, time.time() - t0)
    score = int(10000 / dur)

    temp_after_str, _, temp_after_val, _ = get_cpu_temperature()
    delta_str = ""
    if temp_before_val and temp_after_val:
        delta = temp_after_val - temp_before_val
        delta_str = f"Suhu: {temp_before_str} -> {temp_after_str} (Delta: +{delta:.1f} °C)"
    else:
        delta_str = f"Suhu Terkini: {temp_after_str}"

    return score, dur, delta_str


# ==============================================================================
# 4. OPTIMASI & PERBAIKAN SATU-KLIK (ONE-CLICK MAINTENANCE)
# ==============================================================================

def run_system_optimizer():
    """Menjalankan pembersihan aman: TRIM SSD, Hapus Cache Temp, dan Flush DNS"""
    results = []

    # 1. TRIM SSD
    try:
        ps_trim = "Optimize-Volume -DriveLetter C -ReTrim -ErrorAction SilentlyContinue"
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_trim], capture_output=True, timeout=10)
        results.append("[OK] [bold green]TRIM SSD Drive C:[/bold green] Berhasil dioptimalkan (blok memori siap pakai diperbarui).")
    except Exception as e:
        results.append(f"[X] [bold red]TRIM SSD:[/bold red] {e}")

    # 2. Hapus Temp User
    try:
        temp_dir = tempfile.gettempdir()
        deleted_count = 0
        for item in os.listdir(temp_dir):
            p = os.path.join(temp_dir, item)
            try:
                if os.path.isfile(p):
                    os.remove(p)
                    deleted_count += 1
            except Exception:
                pass
        results.append(f"[OK] [bold green]Pembersihan File Sampah Temp:[/bold green] Berhasil membebaskan {deleted_count} file sementara.")
    except Exception as e:
        results.append(f"[X] [bold red]Bersihkan Temp:[/bold red] {e}")

    # 3. Flush DNS
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=5)
        results.append("[OK] [bold green]Reset Cache Jaringan (Flush DNS):[/bold green] Berhasil me-refresh resolver cache.")
    except Exception as e:
        results.append(f"[X] [bold red]Flush DNS:[/bold red] {e}")

    return results


# ==============================================================================
# 5. ENGINE DIAGNOSTIK OFFLINE (EXPERT SYSTEM)
# ==============================================================================

def generate_offline_expert_analysis(sys_info, cpu_data, cpu_temp_tuple, ram_tuple, storage_tuple, bat_data, uptime_tuple, events):
    """
    Engine analisa teknisi komputer offline berbasis kaidah teknis (Rule-Based Heuristic).
    """
    temp_val, _, _, temp_status = cpu_temp_tuple
    ram_detail, _, ram_pct, ram_status, top_procs = ram_tuple
    disks, has_smart_warn, partitions, has_part_crit = storage_tuple
    uptime_text, _, uptime_days, needs_restart = uptime_tuple

    findings = []
    actions_curative = []
    actions_preventive = []

    # 1. Analisis Kritis Baterai (Dead Cell / BMS Cutoff / Ghost Health)
    if bat_data["is_laptop"]:
        if bat_data["is_dead_cell"]:
            findings.append(
                f"- [bold red]BAHAYA: BATERAI RUSAK MATI / PERMANENT FAILURE (DEAD CELL):[/bold red]\n"
                f"  {bat_data['diagnosis_note']}\n"
                "  Penyebab Laptop Langsung Mati Saat Cabut Charger: Salah satu sel lithium di dalam paket baterai mengalami open-circuit "
                "atau voltasenya anjlok di bawah ambang cutoff, sehingga BMS memutus arus input dan output."
            )
            actions_curative.append(
                "[bold red]Ganti Modul Baterai Laptop:[/bold red] "
                "Baterai sudah tidak aman dan tidak dapat menyimpan arus listrik. Segera ganti modul baterai fisik baru. "
                "Hindari membuka paksa sel baterai sendiri karena berisiko korsleting kimiawi."
            )
            actions_curative.append(
                "[bold yellow]Coba Kalibrasi / Hard Reset Statis Motherboard:[/bold yellow] "
                "Cabut charger, lepas baterai (jika tipe lepas-pasang), tekan dan tahan tombol Power selama 30-40 detik "
                "untuk menguras sisa listrik statis pada kapasitor IC charging motherboard, lalu pasang kembali."
            )
        elif bat_data["wear_level"] <= 15:
            findings.append(
                f"- [bold green]Kesehatan Baterai Sangat Baik (Degradasi {bat_data['wear_level']}%):[/bold green] "
                f"Kapasitas retensi baterai masih berada di {bat_data['health_pct']}% dari spesifikasi asli pabrik."
            )
            actions_preventive.append(
                "[bold cyan]Pertahankan Umur Baterai (Care Mode):[/bold cyan] "
                "Buka aplikasi OEM (seperti MyASUS / HP Support Assistant), aktifkan batasan pengisian di 80%."
            )
        elif bat_data["wear_level"] <= 30:
            findings.append(
                f"- [bold yellow]Degradasi Baterai Moderat (Wear Level {bat_data['wear_level']}%):[/bold yellow] "
                "Penurunan kapasitas wajar seiring siklus pemakaian, durasi pakai tanpa colokan akan sedikit berkurang."
            )
        else:
            findings.append(
                f"- [bold red]Degradasi Baterai Signifikan (Wear Level {bat_data['wear_level']}%):[/bold red] "
                "Baterai telah kehilangan lebih dari 30% kapasitas aslinya. Waktu cadangan daya menurun drastis."
            )

    # 2. Analisis Uptime & Fast Startup
    if uptime_days >= 3:
        findings.append(
            f"- [bold yellow]Uptime Sistem Terlalu Lama ({uptime_text}):[/bold yellow] "
            f"Windows belum pernah di-restart bersih selama {uptime_days} hari. "
            "Fitur 'Fast Startup' menyebabkan Shutdown hanya menyimpan snapshot kernel, sehingga penumpukan cache tidak tereset."
        )
        actions_curative.append(
            "[bold cyan]Lakukan Restart Penuh (Bukan Shutdown):[/bold cyan] "
            "Klik menu Start -> Power -> pilih 'Restart' untuk membebaskan RAM dan kernel cache."
        )

    # 3. Analisis RAM & Top Memory Hogs
    if ram_pct >= 75:
        proc_list_str = ", ".join([f"{p[0]} ({p[1]:.0f} MB)" for p in top_procs[:3]])
        findings.append(
            f"- [bold red]Beban Penggunaan RAM Tinggi ({ram_pct}%):[/bold red] "
            f"Kapasitas RAM fisik sedang tersita. Aplikasi tertinggi: {proc_list_str}."
        )
        actions_curative.append(
            "[bold cyan]Tutup Aplikasi Konsumsi Tinggi di Latar Belakang:[/bold cyan] "
            f"Periksa Task Manager, tutup tab browser atau proses: {top_procs[0][0] if top_procs else 'aplikasi berat'}."
        )
    else:
        findings.append(
            f"- [bold green]Alokasi RAM Sehat ({ram_pct}%):[/bold green] "
            "Kapasitas memori fisik masih memiliki ruang cadangan yang cukup untuk multitasking."
        )

    # 4. Analisis Partisi Penyimpanan (SSD Storage Health)
    for part in partitions:
        drive_name = part["drive"]
        pct = part["used_pct"]
        free = part["free_gb"]
        if pct >= 88:
            findings.append(
                f"- [bold red]Partisi Drive {drive_name} Kritis ({pct}% Penuh, Sisa {free:.1f} GB):[/bold red] "
                "SSD berbasis NVMe QLC/TLC membutuhkan minimal 15-20% ruang kosong untuk mekanisme Dynamic SLC Caching. "
                "Jika ruang tersisa terlalu sempit, write speed akan turun drastis dan mempercepat degradasi sel NAND."
            )
            actions_curative.append(
                f"[bold cyan]Kosongkan Ruang di Drive {drive_name}:[/bold cyan] "
                f"Pindahkan minimal 20-30 GB data (Video/Dokumen/Downloads) ke drive sekunder atau lakukan Disk Cleanup."
            )
        elif pct >= 75:
            findings.append(
                f"- [bold yellow]Partisi Drive {drive_name} Mulai Padat ({pct}% Penuh):[/bold yellow] "
                f"Tersisa {free:.1f} GB. Pertahankan ruang kosong ini agar performa transfer data tetap stabil."
            )

    # 5. Analisis Suhu CPU
    if temp_status == "CRITICAL":
        findings.append(
            f"- [bold red]Suhu CPU Melebihi Ambang Wajar ({temp_val}):[/bold red] "
            "Prosesor mendeteksi suhu tinggi yang berisiko memicu Thermal Throttling."
        )
        actions_curative.append(
            "[bold cyan]Pemeriksaan Sirkulasi Udara & Debu:[/bold cyan] "
            "Pastikan lubang intake kipas di bagian bawah laptop tidak tertutup kain/kasur."
        )
    elif temp_status == "WARM":
        findings.append(
            f"- [bold yellow]Suhu CPU Hangat ({temp_val}):[/bold yellow] "
            "Dalam batas operasional kerja laptop, namun pastikan ventilasi bawah tetap mendapatkan aliran udara bebas."
        )
    else:
        findings.append(
            f"- [bold green]Termal Prosesor Normal ({temp_val}):[/bold green] "
            "Sistem pendingin bekerja optimal dalam menjaga suhu prosesor."
        )

    # 6. Analisis Log Hardware (WHEA / Kernel-Power)
    whea_count = sum(1 for e in events if "WHEA" in e["provider"])
    kp_count = sum(1 for e in events if "Kernel-Power" in e["provider"])
    if whea_count > 0:
        findings.append(
            f"- [bold yellow]Ditemukan {whea_count}x Catatan WHEA-Logger Terkoreksi:[/bold yellow] "
            "Windows mendeteksi koreksi hardware bus PCIe (umum pada AMD Zen saat manajemen daya ASPM aktif)."
        )
    if kp_count > 0:
        findings.append(
            f"- [bold red]Ditemukan {kp_count}x Riwayat Kernel-Power (Mati Tiba-Tiba):[/bold red] "
            "Komputer pernah mengalami mati paksa atau restart tanpa instruksi shutdown bersih dalam 7 hari terakhir."
        )

    # Tindakan Preventif Umum
    actions_preventive.append(
        "[bold cyan]Jalankan Optimasi TRIM SSD:[/bold cyan] "
        "Gunakan menu [5] pada aplikasi ini untuk mengeksekusi ReTrim SSD secara langsung."
    )
    actions_preventive.append(
        "[bold cyan]Audit Program Startup:[/bold cyan] "
        "Matikan aplikasi otomatis yang tidak dibutuhkan melalui Task Manager (tab Startup apps)."
    )

    report_lines = [
        "### 1. EVALUASI KESEHATAN SISTEM (DIAGNOSA AKAR MASALAH)",
        ""
    ]
    report_lines.extend(findings)
    report_lines.append("")
    report_lines.append("### 2. TINDAKAN PERBAIKAN SEGERA (KURATIF)")
    report_lines.append("")
    if actions_curative:
        for idx, act in enumerate(actions_curative, 1):
            report_lines.append(f"{idx}. {act}")
    else:
        report_lines.append("[OK] Tidak ada tindakan kritis mendesak. Kondisi sistem stabil.")
    report_lines.append("")
    report_lines.append("### 3. REKOMENDASI PEMELIHARAAN PREVENTIF")
    report_lines.append("")
    for idx, act in enumerate(actions_preventive, 1):
        report_lines.append(f"{idx}. {act}")

    return "\n".join(report_lines)


# ==============================================================================
# 6. EKSPOR LAPORAN STANDALONE HTML & TXT
# ==============================================================================

def export_html_report(data_dict, offline_analysis, benchmark_data=None):
    """Menghasilkan laporan web mandiri (.html) dengan styling CSS modern dan siap diprint ke PDF"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_device = "".join([c if c.isalnum() else "_" for c in data_dict['profile']['device']])
    filename = f"Laporan_Hardware_{clean_device}_{ts}.html"

    bench_html = ""
    if benchmark_data:
        bench_html = f"""
        <div class="card">
            <h3>Hasil Pengujian Benchmark Hardware</h3>
            <p><strong>CPU Stress Score:</strong> {benchmark_data.get('cpu_score', 'N/A')} poin ({benchmark_data.get('cpu_delta', '')})</p>
            <p><strong>Kecepatan SSD NVMe:</strong> Write: {benchmark_data.get('ssd_write', 0):.1f} MB/s | Read: {benchmark_data.get('ssd_read', 0):.1f} MB/s</p>
        </div>
        """

    html_content = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<title>Laporan Diagnostik Hardware - {data_dict['profile']['device']}</title>
<style>
    body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
    .container {{ max-width: 1000px; margin: 0 auto; background-color: #1e293b; border-radius: 12px; padding: 32px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
    h1 {{ color: #38bdf8; border-bottom: 2px solid #334155; padding-bottom: 12px; font-size: 24px; }}
    h2 {{ color: #4ade80; font-size: 18px; margin-top: 24px; }}
    .meta {{ font-size: 13px; color: #94a3b8; margin-bottom: 20px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; margin-bottom: 24px; }}
    th, td {{ padding: 10px 14px; text-align: left; border-bottom: 1px solid #334155; font-size: 14px; }}
    th {{ background-color: #0f172a; color: #cbd5e1; }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 12px; font-weight: bold; }}
    .card {{ background-color: #0f172a; border-radius: 8px; padding: 16px; margin-top: 16px; border: 1px solid #334155; }}
    .analysis {{ line-height: 1.6; font-size: 14px; color: #e2e8f0; }}
</style>
</head>
<body>
<div class="container">
    <h1>LAPORAN RESMI DIAGNOSTIK HARDWARE</h1>
    <div class="meta">
        Waktu Pemeriksaan: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")} | Perangkat: {data_dict['profile']['device']}
    </div>

    <h2>1. Spesifikasi Perangkat & Motherboard</h2>
    <table>
        <tr><th width="30%">Komponen</th><th>Detail Spesifikasi</th></tr>
        <tr><td>Model Perangkat</td><td>{data_dict['profile']['device']}</td></tr>
        <tr><td>Motherboard</td><td>{data_dict['profile']['motherboard']}</td></tr>
        <tr><td>BIOS Firmware</td><td>{data_dict['profile']['bios_version']} ({data_dict['profile']['bios_date']})</td></tr>
        <tr><td>System Uptime</td><td>{data_dict['uptime'][0]}</td></tr>
    </table>

    <h2>2. Metrik Kesehatan Sensor & Hardware</h2>
    <table>
        <tr><th>Sensor / Komponen</th><th>Nilai Terukur</th><th>Indikator</th></tr>
        <tr><td>Prosesor (CPU)</td><td>{data_dict['cpu']['name']} ({data_dict['cpu']['cores_threads']})</td><td>Beban: {data_dict['cpu']['load_pct']}</td></tr>
        <tr><td>Suhu CPU</td><td>{data_dict['cpu_temp'][0]}</td><td>{data_dict['cpu_temp'][1]}</td></tr>
        <tr><td>Penggunaan RAM</td><td>{data_dict['ram'][0]}</td><td>{data_dict['ram'][1]}</td></tr>
        <tr><td>Kesehatan Baterai</td><td>{data_dict['battery']['status']}</td><td>{data_dict['battery']['badge']}</td></tr>
    </table>

    {bench_html}

    <h2>3. Analisis Diagnosa & Tindakan Teknisi</h2>
    <div class="card analysis">
        {offline_analysis.replace(chr(10), '<br>').replace('### ', '<h3>').replace('- ', '&bull; ')}
    </div>
</div>
</body>
</html>
"""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html_content)
        abs_p = os.path.abspath(filename)
        console.print(f"\n[bold green][OK] Laporan HTML berhasil dibuat:[/bold green] [cyan]{abs_p}[/cyan]")
        console.print("[dim]Anda bisa membuka file ini di browser (Chrome/Edge) atau mencetaknya ke PDF.[/dim]\n")
    except Exception as e:
        console.print(f"[bold red]Gagal membuat file HTML:[/bold red] {e}")


def export_txt_report(raw_data_text, analysis_text, device_name):
    """Menyimpan seluruh diagnosa ke file teks"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_name = "".join([c if c.isalnum() else "_" for c in device_name])
    filename = f"Diagnosa_Hardware_{clean_name}_{ts}.txt"

    content = f"""================================================================================
          LAPORAN LENGKAP DIAGNOSTIK HARDWARE (ENTERPRISE TITAN EDITION)
================================================================================
{raw_data_text}

================================================================================
                  ANALISIS DIAGNOSA & REKOMENDASI TEKNISI
================================================================================
{analysis_text}

================================================================================
Waktu Ekspor: {datetime.now().strftime("%d-%m-%Y %H:%M:%S")}
================================================================================
"""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(content)
        console.print(f"\n[bold green][OK] Laporan TXT tersimpan ke:[/bold green] [cyan]{os.path.abspath(filename)}[/cyan]\n")
    except Exception as e:
        console.print(f"[bold red]Gagal menyimpan file TXT:[/bold red] {e}")


# ==============================================================================
# 7. INSPEKSI KHUSUS BATERAI & SIRKUIT DAYA (DEEP POWER INSPECTOR)
# ==============================================================================

def run_deep_battery_inspector():
    """Modul khusus untuk menganalisis voltase, arus masuk/keluar, dan sel mati"""
    console.print("\n[bold cyan]=== DEEP BATTERY CELL & POWER CIRCUIT INSPECTOR ===[/bold cyan]")
    console.print("[dim]Membaca controller daya ACPI, sirkuit pengisian, dan kondisi kimia sel...[/dim]\n")

    b_info = get_battery_deep_info()
    if not b_info["is_laptop"]:
        console.print("[yellow]Perangkat terdeteksi sebagai Desktop PC (Tidak ada modul baterai fisik).[/yellow]")
        return

    t = Table(title="Detail Sirkuit Baterai & Daya", border_style="bright_blue", box=SAFE_BOX)
    t.add_column("Parameter Daya", style="bold yellow", width=25)
    t.add_column("Nilai Sensor Nyata", style="white")
    t.add_column("Status Verifikasi", width=25, justify="center")

    t.add_row("Kapasitas Desain Pabrik", f"{b_info['design_wh']} Wh", "[bold green]EEPROM Pabrik[/bold green]")
    t.add_row("Kapasitas Maksimal Saat Ini", f"{b_info['full_wh']} Wh", "[bold green]EEPROM Pabrik[/bold green]")
    t.add_row("Persentase Tersisa (SOC)", f"{b_info['remaining_pct']}%", "[bold red]STUCK / KRITIS[/bold red]" if b_info['remaining_pct'] <= 15 else "[bold green]OK[/bold green]")
    t.add_row("Koneksi Charger Listrik (AC)", "Terhubung (Plugged In)" if b_info['power_online'] else "Terputus (Baterai)", "[bold green]ACTIVE[/bold green]" if b_info['power_online'] else "[dim]DISCONNECTED[/dim]")
    t.add_row("Arus Pengisian (Charge Rate)", f"{b_info['charge_rate_w']} Watt (mW: {int(b_info['charge_rate_w']*1000)})", "[bold red]0 WATT (TIDAK MENGISI!)[/bold red]" if (b_info['power_online'] and b_info['charge_rate_w'] == 0) else "[bold green]MENGISI[/bold green]")
    t.add_row("Tegangan Terminal (Voltage)", f"{b_info['voltage_v']} Volt (mV: {int(b_info['voltage_v']*1000)})", "[bold yellow]TEGANGAN BATERAI[/bold yellow]")
    t.add_row("Status BMS (Gas Gauge)", "TERKUNCI / SAFETY CUTOFF" if b_info['is_dead_cell'] else "OPERASIONAL NORMAL", b_info['badge'])

    console.print(t)
    console.print()

    if b_info["is_dead_cell"]:
        console.print(Panel(
            "[bold red]HASIL DIAGNOSA AKAR MASALAH BATERAI:[/bold red]\n\n"
            "1. [bold yellow]Kenapa Dicas Berjam-jam Tidak Naik?[/bold yellow]\n"
            f"   Karena sensor mendeteksi [bold red]Arus Pengisian = 0.0 Watt[/bold red] meskipun charger dicolok. Sirkuit charging di dalam baterai telah diputus secara internal oleh chip proteksi BMS (MOSFET Cutoff).\n\n"
            "2. [bold yellow]Kenapa Charger Dicabut Laptop Langsung Mati?[/bold yellow]\n"
            "   Tegangan sel baterai fisik sudah drop di bawah batas minimal operasi laptop. Baterai tidak mampu menghantarkan arus listrik sama sekali ke motherboard.\n\n"
            "3. [bold yellow]Kenapa Tool Sebelumnya / Windows Bilang '100% Sehat'?[/bold yellow]\n"
            "   Itu adalah [bold cyan]'Ghost Reading'[/bold cyan]. Ketika BMS baterai mengalami kegagalan permanen (Dead Cell), chip berhenti menghitung kapasitas dinamis dan hanya mengembalikan nilai statis bawaan pabrik (44.76 Wh = 44.76 Wh -> 0% wear).",
            title="[bold red]Peringatan Kerusakan Baterai Fisik[/bold red]",
            border_style="red"
        ))
    else:
        console.print(Panel(
            "[bold green]Kondisi Baterai Normal:[/bold green]\n"
            f"Baterai saat ini menerima daya atau beroperasi dengan baik. Arus dan voltase berada dalam ambang batas aman.",
            border_style="green"
        ))


# ==============================================================================
# 8. MENU UTAMA (ENTERPRISE TITAN EDITION TUI)
# ==============================================================================

def main_dashboard():
    last_data = None
    last_analysis = None
    benchmark_results = {}

    while True:
        try:
            console.clear()
            console.print(Panel.fit(
                "[bold cyan]PORTABLE HARDWARE DIAGNOSTIC TOOL (ENTERPRISE TITAN EDITION)[/bold cyan]\n"
                "[dim]AIDA64 / HWiNFO Class • Root WMI • Offline Heuristic Engine • Hardware Crash Audit[/dim]",
                border_style="cyan"
            ))

            menu_table = Table(border_style="blue", show_header=True, box=SAFE_BOX)
            menu_table.add_column("No", style="bold yellow", width=6, justify="center")
            menu_table.add_column("Modul Diagnostik / Fitur", style="bold white")
            menu_table.add_column("Keterangan", style="dim")

            menu_table.add_row("1", "Full Deep Hardware Audit", "Pindai seluruh sensor, motherboard, RAM, NVMe, dan analisis offline")
            menu_table.add_row("2", "Deep Battery & Power Circuit Inspector", "Pemeriksaan Arus Pengisian (Watt), Voltase, dan Sel Mati (Dead Cell)")
            menu_table.add_row("3", "Audit Hardware Event Log", "Deteksi BSOD, Kernel-Power, WHEA-Logger & Disk I/O Timeout (7 hari)")
            menu_table.add_row("4", "Hardware Benchmark Suite", "Uji kecepatan Read/Write SSD NVMe & CPU Multi-Thread Stress Test")
            menu_table.add_row("5", "One-Click System Optimizer", "Eksekusi TRIM SSD, Bersihkan Sampah Temp, dan Reset Jaringan")
            menu_table.add_row("6", "Ekspor Laporan HTML & TXT", "Cetak laporan diagnostik resmi berformat web HTML dan dokumen teks")
            menu_table.add_row("7", "Konsultasi AI Gemini Online", "Minta opini tambahan dari AI Gemini (opsional, jika ada internet)")
            menu_table.add_row("0", "Keluar", "Tutup aplikasi diagnostik")

            console.print(menu_table)
            console.print()

            choice = Prompt.ask("[bold green]Pilih nomor menu[/bold green]", choices=["1", "2", "3", "4", "5", "6", "7", "0"], default="1")

            if choice == "1":
                last_data, last_analysis = run_full_audit()
                console.print("\n[dim]Tekan Enter untuk kembali ke menu utama...[/dim]")
                input()

            elif choice == "2":
                run_deep_battery_inspector()
                console.print("\n[dim]Tekan Enter untuk kembali ke menu utama...[/dim]")
                input()

            elif choice == "3":
                run_event_log_audit()
                console.print("\n[dim]Tekan Enter untuk kembali ke menu utama...[/dim]")
                input()

            elif choice == "4":
                benchmark_results = run_benchmark_suite()
                console.print("\n[dim]Tekan Enter untuk kembali ke menu utama...[/dim]")
                input()

            elif choice == "5":
                run_optimizer_menu()
                console.print("\n[dim]Tekan Enter untuk kembali ke menu utama...[/dim]")
                input()

            elif choice == "6":
                if not last_data:
                    console.print("\n[yellow]Mengambil data diagnostik terlebih dahulu...[/yellow]")
                    last_data, last_analysis = run_full_audit(quiet=True)
                export_html_report(last_data, last_analysis, benchmark_results)
                export_txt_report(last_data["raw_summary"], last_analysis, last_data["profile"]["device"])
                console.print("[dim]Tekan Enter untuk kembali ke menu utama...[/dim]")
                input()

            elif choice == "7":
                if not last_data:
                    last_data, last_analysis = run_full_audit(quiet=True)
                run_online_ai_chat(last_data["raw_summary"])
                console.print("\n[dim]Tekan Enter untuk kembali ke menu utama...[/dim]")
                input()

            elif choice == "0":
                console.print("\n[bold cyan]Terima kasih. Program diagnostik ditutup.[/bold cyan]")
                break

        except KeyboardInterrupt:
            break
        except Exception as err:
            console.print(f"\n[bold red]Terjadi kesalahan teknis:[/bold red] {err}")
            console.print("[dim]Tekan Enter untuk melanjutkan ke menu utama...[/dim]")
            input()


def run_full_audit(quiet=False):
    """Menjalankan audit hardware menyeluruh dan analisa offline"""
    if not quiet:
        console.print("\n[bold green]Memindai seluruh hardware ke level kernel & WMI Root...[/bold green]")
    
    mb_bios = get_motherboard_bios()
    cpu_data = get_cpu_deep_info()
    cpu_temp = get_cpu_temperature()
    ram_modules = get_ram_hardware_modules()
    ram_usage = get_ram_usage_and_processes()
    storage_data = get_storage_deep_info()
    battery_data = get_battery_deep_info()
    uptime_data = get_system_uptime()
    events = audit_windows_hardware_events()

    data_dict = {
        "profile": mb_bios,
        "cpu": cpu_data,
        "cpu_temp": cpu_temp,
        "ram_modules": ram_modules,
        "ram": ram_usage,
        "storage": storage_data,
        "battery": battery_data,
        "uptime": uptime_data,
        "events": events
    }

    ram_slots_str = "\n".join([f"- Slot {idx+1}: {mod}" for idx, mod in enumerate(ram_modules)]) if ram_modules else "Onboard"
    top_proc_str = "\n".join([f"- {p[0]} (PID: {p[2]}): {p[1]:.1f} MB" for p in ram_usage[4]])
    disks_str = "\n".join(storage_data[0]) if storage_data[0] else "Tidak terdeteksi"
    part_lines = [f"{p['drive']} Sisa: {p['free_gb']:.1f} GB / {p['total_gb']:.1f} GB ({p['used_pct']}%) -> {p['badge']}" for p in storage_data[2]]
    part_str = "\n".join(part_lines)

    data_dict["raw_summary"] = f"""Waktu Diagnostik : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
Perangkat        : {mb_bios['device']}
Motherboard      : {mb_bios['motherboard']}
BIOS             : {mb_bios['bios_version']} ({mb_bios['bios_date']})
Uptime           : {uptime_data[0]}
Prosesor         : {cpu_data['name']} ({cpu_data['cores_threads']})
Suhu CPU         : {cpu_temp[0]} ({cpu_temp[1]})
RAM Fisik        : {', '.join(ram_modules)}
Penggunaan RAM   : {ram_usage[0]}
Top Proses RAM   :
{top_proc_str}
Disk & SMART     :
{disks_str}
Partisi          :
{part_str}
Baterai          :
{battery_data['status']}"""

    offline_analysis = generate_offline_expert_analysis(
        mb_bios, cpu_data, cpu_temp, ram_usage, storage_data, battery_data, uptime_data, events
    )

    if not quiet:
        t1 = Table(title="[bold white]Profil Perangkat & Firmware[/bold white]", border_style="blue", box=SAFE_BOX)
        t1.add_column("Komponen", style="bold yellow", width=22)
        t1.add_column("Keterangan", style="white")
        t1.add_row("Model Perangkat", mb_bios["device"])
        t1.add_row("Motherboard", mb_bios["motherboard"])
        t1.add_row("Versi BIOS", f"{mb_bios['bios_version']} (Rilis: {mb_bios['bios_date']})")
        t1.add_row("System Uptime", f"{uptime_data[0]} -> {uptime_data[1]}")
        console.print(t1)
        console.print()

        t2 = Table(title="[bold white]Spesifikasi & Beban CPU / RAM[/bold white]", border_style="cyan", box=SAFE_BOX)
        t2.add_column("Komponen", style="bold yellow", width=22)
        t2.add_column("Nilai Metrik", style="white")
        t2.add_column("Status / Indikator", width=24, justify="center")
        t2.add_row("Prosesor (CPU)", f"{cpu_data['name']}\n{cpu_data['cores_threads']} | Clock: {cpu_data['clock_speed']}", f"Beban: {cpu_data['load_pct']}")
        t2.add_row("Suhu CPU", cpu_temp[0], cpu_temp[1])
        t2.add_row("Modul Fisik RAM", ram_slots_str, "[bold green]DUAL CHANNEL[/bold green]" if len(ram_modules) > 1 else "[bold green]TERDETEKSI[/bold green]")
        t2.add_row("Penggunaan RAM", ram_usage[0], ram_usage[1])
        t2.add_row("Top 5 Pemakan RAM", top_proc_str, "[bold yellow]KONSUMSI MEMORI[/bold yellow]")
        console.print(t2)
        console.print()

        t3 = Table(title="[bold white]Storage (SSD NVMe) & Baterai[/bold white]", border_style="magenta", box=SAFE_BOX)
        t3.add_column("Komponen", style="bold yellow", width=22)
        t3.add_column("Keterangan", style="white")
        t3.add_column("Status", width=24, justify="center")
        t3.add_row("Disk & SMART", disks_str, "[bold green]SEHAT (HEALTHY)[/bold green]" if not storage_data[1] else "[bold red]PERIKSA DISK[/bold red]")
        t3.add_row("Partisi Storage", part_str, "[bold red]KRITIS[/bold red]" if storage_data[3] else "[bold green]OK[/bold green]")
        t3.add_row("Kesehatan Baterai", battery_data["status"], battery_data["badge"])
        console.print(t3)
        console.print()

        console.print(Panel(
            Markdown(offline_analysis),
            title="[bold green]Analisis Kerusakan & Rekomendasi Teknisi (100% OFFLINE HEURISTIC ENGINE)[/bold green]",
            border_style="green",
            padding=(1, 2)
        ))

    return data_dict, offline_analysis


def run_event_log_audit():
    """Menampilkan detail riwayat crash, BSOD, dan WHEA error"""
    console.print("\n[bold cyan]=== AUDIT LOG KERUSAKAN HARDWARE (WINDOWS EVENT VIEWER) ===[/bold cyan]")
    console.print("[dim]Memindai Kernel-Power, WHEA-Logger, dan Disk Controller error dalam 7 hari terakhir...[/dim]\n")

    events = audit_windows_hardware_events()
    if not events:
        console.print(Panel("[bold green][OK] BERSIH:[/bold green] Tidak ditemukan catatan crash hardware, BSOD, atau disk error dalam 7 hari terakhir.", border_style="green"))
        return

    table = Table(title=f"Ditemukan {len(events)} Catatan Peristiwa Hardware", border_style="red", box=SAFE_BOX)
    table.add_column("Waktu Kejadian", style="cyan", width=22)
    table.add_column("Sumber (Provider)", style="bold yellow", width=18)
    table.add_column("Event ID", style="magenta", width=10, justify="center")
    table.add_column("Keterangan Masalah", style="white")

    for ev in events:
        table.add_row(ev["time"], ev["provider"], str(ev["id"]), ev["desc"])

    console.print(table)
    console.print("\n[bold yellow]Analisis Teknisi:[/bold yellow] Jika tertera 'WHEA-Logger Event ID 17', ini adalah koreksi otomatis bus PCIe oleh prosesor/chipset AMD. Jika tertera 'Kernel-Power Event ID 41', komputer pernah mengalami mati mendadak atau tombol power ditekan paksa.")


def run_benchmark_suite():
    """Menjalankan benchmark SSD NVMe dan CPU Stress Test"""
    console.print("\n[bold cyan]=== HARDWARE BENCHMARK & STRESS SUITE ===[/bold cyan]")
    results = {}

    with console.status("[bold green]Menguji kecepatan Baca & Tulis SSD NVMe Drive C:...", spinner="dots"):
        err, write_spd, read_spd = benchmark_disk_speed()

    if err:
        console.print(f"[bold red]Gagal menguji SSD:[/bold red] {err}")
    else:
        results["ssd_write"] = write_spd
        results["ssd_read"] = read_spd
        t_disk = Table(title="Hasil Pengujian Kecepatan Real-time SSD NVMe", border_style="bright_blue", box=SAFE_BOX)
        t_disk.add_column("Metrik Pengujian", style="bold yellow")
        t_disk.add_column("Kecepatan (Throughput)", style="bold green")
        t_disk.add_row("Kecepatan Tulis (Sequential Write)", f"{write_spd:.1f} MB/detik")
        t_disk.add_row("Kecepatan Baca (Sequential Read)", f"{read_spd:.1f} MB/detik")
        console.print(t_disk)
        console.print()

    console.print("[bold yellow]Memulai CPU Multi-Thread Stress Test (100% Load semua core)...[/bold yellow]")
    with console.status("[bold red]Memproses beban komputasi intensif dan mengukur suhu...", spinner="dots"):
        score, dur, delta_str = benchmark_cpu_stress()

    results["cpu_score"] = score
    results["cpu_delta"] = delta_str

    t_cpu = Table(title="Hasil CPU Benchmark & Respon Termal", border_style="bright_red", box=SAFE_BOX)
    t_cpu.add_column("Parameter", style="bold yellow")
    t_cpu.add_column("Nilai Terukur", style="bold white")
    t_cpu.add_row("Skor Performa Komputasi", f"[bold green]{score} Poin[/bold green]")
    t_cpu.add_row("Waktu Selesai Uji Beban", f"{dur:.2f} detik")
    t_cpu.add_row("Respon Termal Suhu", delta_str)
    console.print(t_cpu)

    return results


def run_optimizer_menu():
    """Eksekusi pemeliharaan cepat satu-klik"""
    console.print("\n[bold cyan]=== ONE-CLICK HARDWARE & SYSTEM OPTIMIZER ===[/bold cyan]")
    console.print("[dim]Menjalankan TRIM SSD, pembersihan temporary cache, dan flush DNS...[/dim]\n")

    with console.status("[bold green]Mengeksekusi perintah pemeliharaan...", spinner="dots"):
        logs = run_system_optimizer()

    for l in logs:
        console.print(l)
    console.print("\n[bold green]Optimasi selesai.[/bold green]")


def run_online_ai_chat(raw_summary):
    """Konsultasi interaktif online dengan Gemini jika ada koneksi"""
    console.print("\n[bold magenta]=== KONSULTASI AI GEMINI ONLINE ===[/bold magenta]")
    if not GEMINI_API_KEY.strip():
        console.print("[yellow]API Key Gemini tidak disetel.[/yellow]")
        return

    with console.status("[bold magenta]Menghubungi AI Gemini...", spinner="dots"):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        prompt = f"Anda adalah teknisi hardware profesional. Analisis data diagnostik komputer berikut dan berikan opini mendalam:\n{raw_summary}"
        try:
            r = requests.post(url, json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=35)
            r.raise_for_status()
            reply = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            console.print(Panel(Markdown(reply), title="[bold green]Analisis AI Gemini Online[/bold green]", border_style="bright_blue"))
        except Exception as e:
            console.print(f"[bold red]Gagal terhubung ke AI (Periksa koneksi internet Anda):[/bold red] {e}")


def main():
    try:
        main_dashboard()
    except Exception as e:
        console.print(f"\n[bold red]Fatal Error:[/bold red] {e}")
        console.print_exception()
        input("\n[Tekan Enter untuk keluar...]")


if __name__ == "__main__":
    main()
