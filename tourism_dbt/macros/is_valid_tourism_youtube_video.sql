{% macro is_valid_tourism_youtube_video(category_col='category', title_col='title', channel_col='channel_name') %}
(
    COALESCE({{ category_col }}, '') NOT IN ('Music', 'Gaming', 'Autos & Vehicles', 'Comedy', 'Sports', 'Pets & Animals', 'Film & Animation')
    AND NOT REGEXP_MATCHES(
        LOWER(COALESCE({{ title_col }}, '')),
        '(official mv|music video|official audio|karaoke|remix|parody|nhạc chế|\\blyric\\b|\\blyrics\\b|vietsub|búp bê|thiếu nhi|chữ cái|đồ chơi|cocomelon|nursery rhyme|bunker|nuclear|doomsday|mrbeast|stokes twins|vanh leg|vlad|diana|shaun the sheep|see you again|selena gomez|ed sheeran|sơn tùng|hoà minzy|hòa minzy|bắc bling|bống bống bang bang|lạc trôi|\\bjack\\b|hà anh tuấn|charlie puth|experiment car|water balloons|water park|mini house|gospel for the poor|\\btoy\\b|\\btoys\\b|\\bcheems\\b|oymyakon|con vịt|vịt vàng|anh kết em|two steps from hell|despacito|shape of you|london bridge|đầu đường xó chợ|quân a\\.p|cá lăng|thức giấc|muộn màng|faptv|the playah|tháng tư là lời nói dối|hoa hải đường|đi về nhà|giấc mộng ca sĩ|giang hải không độ nàng|cố giang tình|hiền hồ|vỡ tan|obito|mark rober|oppa huy idol|america''s got talent)'
    )
    AND NOT REGEXP_MATCHES(
        LOWER(COALESCE({{ channel_col }}, '')),
        '(mrbeast|stokes twins|cocomelon|surprisefuntv|vlad|diana|ben azelart|vevo|vanh leg|kênh bé yêu|shaun the sheep|dreamy|music|records|audio|record|noodle & pals|gospel|cheems|faptv|oppa huy idol)'
    )
)
{% endmacro %}
