import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, timezone
import random

light_colors = ["#69CAFF", "#E87361", "#F6E039", "#FF96CC", "#A0FF89"]

if "bg_color" not in st.session_state:
    st.session_state.bg_color = random.choice(light_colors)

bg_color = st.session_state.bg_color

st.markdown(f"""
    <style>
        .stApp {{
            background-color: {bg_color} !important;
            /* 可選：讓背景覆蓋整個視窗 */
            min-height: 100vh;
        }}
    </style>
""", unsafe_allow_html=True)


@st.cache_data
def load_stops():
    df = pd.read_csv("route_stops.csv")
    df = df.dropna(subset=["route_id"])
    df = df.sort_values(by=["route_id", "direction", "order"]).reset_index(drop=True)
    return df


def simulate_full_route_schedule(route_df, selected_route, selected_station, selected_time, rest_minutes=10):
    route_outbound = route_df[(route_df["route_id"] == selected_route) & (route_df["direction"] == 1)].copy()
    route_outbound = route_outbound.sort_values("order").reset_index(drop=True)

    route_return = route_df[(route_df["route_id"] == selected_route) & (route_df["direction"] == 2)].copy()
    route_return = route_return.sort_values("order").reset_index(drop=True)

    full_route = pd.concat([route_outbound.iloc[:-1], route_return], ignore_index=True)
    full_route["full_order"] = range(1, len(full_route) + 1)
    full_route["time_to_next"] = full_route["time_to_next"].fillna(0)
    full_route["cumulative_time"] = full_route["time_to_next"].cumsum()
    full_route.at[0, "cumulative_time"] = 0
    full_route["station_key"] = full_route["stop_name"] + "_order" + full_route["full_order"].astype(str)

    candidate = full_route[full_route["stop_name"] == selected_station]
    if candidate.empty:
        st.error("找不到該站名")
        return pd.DataFrame(), pd.DataFrame()

    selected_dt = datetime.combine(datetime.today(), selected_time)
    base_row = candidate.iloc[0]
    base_cum_time = base_row["cumulative_time"]
    base_station_key = base_row["station_key"]
    start_departure_dt = selected_dt - timedelta(minutes=base_cum_time)

    trip_duration = full_route["time_to_next"].sum()
    interval = trip_duration + rest_minutes
    day_start = datetime.combine(datetime.today(), datetime.strptime("05:00", "%H:%M").time())
    day_end = datetime.combine(datetime.today(), datetime.strptime("23:59", "%H:%M").time())

    while start_departure_dt - timedelta(minutes=interval) >= day_start:
        start_departure_dt -= timedelta(minutes=interval)

    departures = []
    dep = start_departure_dt
    while dep <= day_end:
        departures.append(dep)
        dep += timedelta(minutes=interval)

    schedule_list = []
    for depart_time in departures:
        for _, stop in full_route.iterrows():
            arrival_time = depart_time + timedelta(minutes=stop["cumulative_time"])
            schedule_list.append({
                "station_order": stop["full_order"],
                "station_name": stop["stop_name"],
                "station_key": stop["station_key"],
                "direction": stop["direction"],
                "bus_departure": depart_time,
                "arrival_time": arrival_time
            })

    schedule_df = pd.DataFrame(schedule_list)
    schedule_df["bus_departure_str"] = schedule_df["bus_departure"].dt.strftime("%H:%M")
    schedule_df["arrival_time_str"] = schedule_df["arrival_time"].dt.strftime("%H:%M")

    schedule_df = schedule_df.groupby(
        ["station_key", "station_name", "bus_departure_str", "direction"]
    ).agg({
        "arrival_time_str": "min",
        "station_order": "first"
    }).reset_index()

    pivot = schedule_df.pivot(index="station_key", columns="bus_departure_str", values="arrival_time_str")
    station_order_df = schedule_df[["station_key", "station_order"]].drop_duplicates().set_index("station_key")
    pivot = pivot.loc[station_order_df.sort_values("station_order").index]
    pivot = pivot[sorted(pivot.columns)]

    user_dep_str = (selected_dt - timedelta(minutes=base_cum_time)).strftime("%H:%M")
    cols = list(pivot.columns)
    try:
        user_idx = cols.index(user_dep_str)
    except ValueError:
        user_idx = 0

    for i in range(user_idx):
        val = pivot.at[base_station_key, cols[i]] if base_station_key in pivot.index else None
        if pd.notna(val):
            if val < selected_time.strftime("%H:%M"):
                pivot[cols[i]] = ""

    direction_map = full_route.set_index("station_key")["direction"].to_dict()
    pivot["direction"] = pivot.index.map(direction_map)

    pivot_outbound = pivot[pivot["direction"] == 1].drop(columns=["direction"])
    pivot_return = pivot[pivot["direction"] == 2].drop(columns=["direction"])

    station_name_map = full_route.set_index("station_key")["stop_name"].to_dict()
    pivot_outbound.index = pivot_outbound.index.map(station_name_map)
    pivot_return.index = pivot_return.index.map(station_name_map)

    return pivot_outbound, pivot_return


def main():
    page = st.sidebar.selectbox("選擇頁面", ["MAYDAY EXPRESS 🚌 🚝 時間估算", "MAYDAY EXPRESS 車牌資訊"])

    if page == "MAYDAY EXPRESS 🚌 🚝 時間估算":
        st.title("MAYDAY EXPRESS 🚌 🚝 時間估算")

        df = load_stops()
        route_options = df[["route_id", "route_display"]].drop_duplicates()
        route_dict = dict(zip(route_options["route_display"], route_options["route_id"]))
        selected_display = st.selectbox("選擇路線", route_options["route_display"])
        selected_route = route_dict[selected_display]

        dir_df = df[df["route_id"] == selected_route][["direction", "direction_name"]].drop_duplicates()
        dir_options = dir_df["direction"].tolist()
        dir_labels = dict(zip(dir_df["direction"], dir_df["direction_name"]))

        direction = st.radio("選擇方向", options=dir_options, format_func=lambda x: dir_labels.get(x, f"方向 {x}"))

        stations = df[(df["route_id"] == selected_route) & (df["direction"] == direction)][
            ["order", "stop_name"]].sort_values("order")
        selected_station = st.selectbox("目前所在站", stations["stop_name"].values)

        col1, col2 = st.columns(2)
        hour_options = list(range(24))
        minute_options = list(range(60))
        default_now = datetime.now(timezone.utc) + timedelta(hours=8)
        default_hour = default_now.hour
        default_minute = default_now.minute

        if "selected_hour" not in st.session_state:
            st.session_state.selected_hour = default_hour
        if "selected_minute" not in st.session_state:
            st.session_state.selected_minute = default_minute

        with col1:
            selected_hour = st.selectbox("時", hour_options, index=st.session_state.selected_hour)
        with col2:
            selected_minute = st.selectbox("分", minute_options, index=st.session_state.selected_minute)

        st.session_state.selected_hour = selected_hour
        st.session_state.selected_minute = selected_minute

        now_time = datetime.strptime(f"{selected_hour:02d}:{selected_minute:02d}", "%H:%M").time()

        pivot_outbound, pivot_return = simulate_full_route_schedule(
            df, selected_route, selected_station, now_time
        )

        st.write(f" {dir_labels.get(1, '去程')} ")
        st.dataframe(pivot_outbound, use_container_width=True)

        st.write(f" {dir_labels.get(2, '回程')} ")
        st.dataframe(pivot_return, use_container_width=True)

    elif page == "MAYDAY EXPRESS 車牌資訊":
        st.title("MAYDAY EXPRESS 車牌資訊")
        try:
            df_bus = pd.read_csv("bus_no.csv")
            st.dataframe(df_bus, use_container_width=True, hide_index=True)
        except FileNotFoundError:
            st.error("找不到 bus_no.csv 檔案，請確認檔案存在。")


if __name__ == "__main__":
    main()
