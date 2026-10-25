import os
import unittest
from hardware_diagnostic import (
    get_motherboard_bios,
    get_cpu_deep_info,
    get_cpu_temperature,
    get_ram_hardware_modules,
    get_ram_usage_and_processes,
    get_storage_deep_info,
    get_battery_deep_info,
    get_system_uptime,
    audit_windows_hardware_events,
    generate_offline_expert_analysis,
    benchmark_disk_speed,
    export_html_report,
    export_txt_report
)


class TestHardwareDiagnostic(unittest.TestCase):
    def test_motherboard_bios(self):
        info = get_motherboard_bios()
        self.assertIsInstance(info, dict)
        self.assertIn("device", info)
        self.assertIn("motherboard", info)
        self.assertIn("bios_version", info)
        self.assertIn("bios_date", info)

    def test_cpu_deep_info(self):
        cpu = get_cpu_deep_info()
        self.assertIsInstance(cpu, dict)
        self.assertIn("name", cpu)
        self.assertIn("cores_threads", cpu)
        self.assertIn("load_pct", cpu)

    def test_cpu_temperature(self):
        temp_str, badge, val, status = get_cpu_temperature()
        self.assertIsInstance(temp_str, str)
        self.assertIsInstance(badge, str)
        self.assertIn(status, ["NORMAL", "WARM", "CRITICAL", "UNKNOWN"])

    def test_ram_metrics(self):
        modules = get_ram_hardware_modules()
        self.assertIsInstance(modules, list)

        detail, badge, pct, status, top_5 = get_ram_usage_and_processes()
        self.assertIsInstance(detail, str)
        self.assertIsInstance(pct, (int, float))
        self.assertGreaterEqual(pct, 0)
        self.assertLessEqual(pct, 100)
        self.assertIn(status, ["OK", "WARNING", "CRITICAL", "ERROR"])
        self.assertIsInstance(top_5, list)

    def test_storage_deep_info(self):
        disks, has_smart_warn, partitions, has_part_crit = get_storage_deep_info()
        self.assertIsInstance(disks, list)
        self.assertIsInstance(has_smart_warn, bool)
        self.assertIsInstance(partitions, list)
        self.assertIsInstance(has_part_crit, bool)

    def test_battery_deep_info(self):
        bat = get_battery_deep_info()
        self.assertIsInstance(bat, dict)
        self.assertIn("is_laptop", bat)
        self.assertIn("design_wh", bat)
        self.assertIn("full_wh", bat)
        self.assertIn("health_pct", bat)
        self.assertIn("wear_level", bat)
        self.assertIn("is_dead_cell", bat)

    def test_system_uptime(self):
        text, badge, days, needs_restart = get_system_uptime()
        self.assertIsInstance(text, str)
        self.assertIsInstance(days, int)
        self.assertIsInstance(needs_restart, bool)
        self.assertGreaterEqual(days, 0)

    def test_event_log_audit(self):
        events = audit_windows_hardware_events()
        self.assertIsInstance(events, list)

    def test_offline_heuristic_expert_analysis(self):
        mb_bios = get_motherboard_bios()
        cpu_data = get_cpu_deep_info()
        cpu_temp = get_cpu_temperature()
        ram_usage = get_ram_usage_and_processes()
        storage_data = get_storage_deep_info()
        battery_data = get_battery_deep_info()
        uptime_data = get_system_uptime()
        events = audit_windows_hardware_events()

        analysis = generate_offline_expert_analysis(
            mb_bios, cpu_data, cpu_temp, ram_usage, storage_data, battery_data, uptime_data, events
        )
        self.assertIsInstance(analysis, str)
        self.assertIn("EVALUASI KESEHATAN SISTEM", analysis)
        self.assertIn("TINDAKAN PERBAIKAN SEGERA", analysis)
        self.assertIn("REKOMENDASI PEMELIHARAAN PREVENTIF", analysis)

    def test_storage_benchmark(self):
        err, write_spd, read_spd = benchmark_disk_speed()
        self.assertIsNone(err)
        self.assertGreater(write_spd, 0)
        self.assertGreater(read_spd, 0)


if __name__ == "__main__":
    unittest.main()
