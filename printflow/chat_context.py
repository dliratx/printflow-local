"""Small navigation summaries; full inspection and emitted settings stay in job_status."""
from __future__ import annotations


def pick(value, keys):
    return {key: value[key] for key in keys if key in value}


def job_summary(job):
    result = pick(job, ('id', 'file_id', 'filename', 'status', 'stage', 'progress',
                        'created_at', 'completed_at', 'comparison_id', 'child_job_ids',
                        'variant_name', 'profile_id', 'printer_id', 'print_outcome'))
    if job.get('error'):
        error = str(job['error'])
        result['error'] = error[:1000]
        if len(error) > 1000: result['error_truncated'] = True
    output = job.get('result') or {}
    if output:
        result['result'] = pick(output, ('status', 'project', 'review_required'))
        result['result']['plates'] = [pick(plate, ('gcode', 'estimated_print_time',
            'estimated_seconds', 'total_filament_grams', 'tools_zero_based', 'printer_model',
            'filament_types')) for plate in output.get('plates', [])]
    return result


def file_summary(file):
    if not file: return None
    result = pick(file, ('id', 'name', 'path', 'extension', 'folder', 'size'))
    if file.get('preview'):
        result['preview'] = pick(file['preview'], ('dimensions', 'dimensions_mm',
            'triangle_count', 'object_count', 'colors', 'color_count', 'preparation_supported'))
    return result


def printer_summary(printer):
    # Preserve observed inventory and freshness, omit duplicated firmware/raw payloads.
    return pick(printer, ('id', 'name', 'kind', 'updated_at', 'connected', 'state',
        'filename', 'progress', 'eta_seconds', 'active_tool_index', 'active_nozzle',
        'temperatures', 'filaments', 'status_message', 'capabilities'))


def chat_context(printers, selected_file, jobs, slicer):
    relevant = [job for job in jobs if selected_file and job.get('file_id') == selected_file['id']]
    chosen = {job['id']: job for job in [*jobs[-4:], *relevant[-4:]]}
    return {'printers': [printer_summary(p) for p in printers],
            'selected_file': file_summary(selected_file),
            'recent_jobs': [job_summary(job) for job in chosen.values()],
            'slicer': slicer,
            'detail_tool': 'Use job_status for complete results and effective settings.'}
