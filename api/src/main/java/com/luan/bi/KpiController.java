package com.luan.bi;

import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

/** Read-only KPI API over the SQL views, so other systems can consume the same definitions as the dashboard. */
@RestController
@RequestMapping("/api")
public class KpiController {
    private final JdbcTemplate jdbc;
    public KpiController(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @GetMapping("/stores")
    public List<Map<String, Object>> stores() {
        return jdbc.queryForList("SELECT * FROM vw_store_summary ORDER BY margin_pct DESC");
    }

    @GetMapping("/stores/{id}/margin")
    public List<Map<String, Object>> margin(@PathVariable String id) {
        return jdbc.queryForList("SELECT * FROM vw_store_margin WHERE store_id = ? ORDER BY year_month", id.toUpperCase());
    }

    @GetMapping("/leakage")
    public List<Map<String, Object>> leakage(@RequestParam(required = false) String month) {
        return month == null
            ? jdbc.queryForList("SELECT * FROM vw_leakage_by_store_month ORDER BY year_month, store_id")
            : jdbc.queryForList("SELECT * FROM vw_leakage_by_store_month WHERE year_month = ? ORDER BY store_id", month);
    }

    @GetMapping("/discrepancies")
    public List<Map<String, Object>> discrepancies(@RequestParam(defaultValue = "25") int limit) {
        return jdbc.queryForList(
            "SELECT * FROM recon_result WHERE status <> 'ok' ORDER BY ABS(variance) DESC LIMIT ?", Math.min(limit, 200));
    }
}
