import json
from datetime import datetime

# Re-parse from page text files with region-grouped structure
dams_by_region = {}

regions = {3: 'नागपूर', 4: 'अमरावती', 5: 'छत्रपती संभाजीनगर', 6: 'छत्रपती संभाजीनगर', 7: 'पुणे', 8: 'पुणे'}

districts = ['भंडारा', 'चंद्रपूर', 'गडचिरोली', 'गोंदिया', 'नागपूर', 'वर्धा',
             'अकोला', 'अमरावती', 'बुलढाणा', 'यवतमाळ', 'छत्रपती संभाजीनगर',
             'बीड', 'हिंगोली', 'नांदेड', 'धाराशिव', 'लातूर', 'परभणी',
             'अहिल्यानगर', 'जळगाव', 'नाशिक', 'कोल्हापूर', 'पुणे', 'सांगली',
             'सातारा', 'सोलापूर', 'पालघर', 'रायगड', 'सिंधुदुर्ग', 'ठाणे']

for i in range(3, 9):
    with open(f'page_{i}.txt', 'r', encoding='utf-8') as f:
        text = f.read()

    lines = text.split('\n')
    current_region = regions.get(i, '')
    current_district = ''

    j = 0
    while j < len(lines):
        line = lines[j].strip()
        j += 1
        if not line:
            continue

        for d in districts:
            if line == d or line.startswith(d + ' '):
                current_district = d
                break

        if line.isdigit() or (len(line) <= 3 and line.replace('ू', '').replace('ं', '').isdigit()):
            serial = line
            if j + 9 < len(lines):
                name = lines[j].strip()
                date = lines[j+1].strip()
                time = lines[j+2].strip()
                dead = lines[j+3].strip()
                live = lines[j+4].strip()
                total = lines[j+5].strip()
                curr_live = lines[j+6].strip()
                curr_total = lines[j+7].strip()
                pct1 = lines[j+8].strip()
                pct2 = lines[j+9].strip()

                def parse_val(v):
                    if not v or not v.strip():
                        return None
                    try:
                        return float(v.replace(',', ''))
                    except:
                        return None

                if name and len(name) > 1 and not name.startswith('एूकण') and not name.startswith('एकूण'):
                    dam = {
                        'dam_name': name,
                        'serial_number': serial,
                        'date': date,
                        'time': time,
                        'dead_storage_mcm': parse_val(dead),
                        'live_storage_mcm': parse_val(live),
                        'total_design_storage_mcm': parse_val(total),
                        'current_live_storage_mcm': parse_val(curr_live),
                        'current_total_storage_mcm': parse_val(curr_total),
                        'percentage_today': pct1,
                        'percentage_last_year': pct2,
                    }

                    region = regions.get(i, '')
                    if region not in dams_by_region:
                        dams_by_region[region] = []
                    dams_by_region[region].append(dam)
                j += 10

# Fix region assignments for pages 7-8
all_dams = []
for region, dams in dams_by_region.items():
    for dam in dams:
        dam['region'] = region
        all_dams.append(dam)

for i, dam in enumerate(all_dams):
    if 72 <= i <= 89:  # Page 7
        dam['region'] = 'पुणे'
    elif 90 <= i < len(all_dams):  # Page 8
        if dam.get('district') in ['रायगड', 'सिंधुदुर्ग', 'ठाणे', 'पालघर']:
            dam['region'] = 'कोकण'
        else:
            dam['region'] = 'पुणे'

# Group by region
regions_output = {}
for dam in all_dams:
    region = dam.get('region', 'Unknown')
    dam.pop('region', None)
    dam.pop('district', None)

    if region not in regions_output:
        regions_output[region] = {'dams': [], 'summaries': [], 'dam_count': 0}
    regions_output[region]['dams'].append(dam)
    regions_output[region]['dam_count'] += 1

# Create final document
now = datetime.utcnow()
report_date = datetime(2026, 10, 11)

doc = {
    'report_date': report_date,
    'created_at': datetime.utcnow(),
    'units': 'MCM',
    'state': 'Maharashtra',
    'regions': regions_output,
}

with open('downloads/extracted_tables_cached.json', 'w', encoding='utf-8') as f:
    json.dump([doc], f, ensure_ascii=False, indent=2, default=str)

print('Cache updated')
for r, data in regions_output.items():
    print(f'  {r}: {data["dam_count"]} dams')