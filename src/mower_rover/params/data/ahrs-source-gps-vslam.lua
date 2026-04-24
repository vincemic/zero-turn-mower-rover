-- ahrs-source-gps-vslam.lua
-- VERSION: 1.0
-- Automatic GPS/VSLAM EKF source switching for zero-turn mower rover.
-- Source Set 1 = GPS (RTK), Source Set 2 = ExternalNav (VSLAM).
-- Runs at 10 Hz on Pixhawk. No dependency on Jetson being alive.

local FREQ_HZ = 10
local SOURCE_GPS = 0    -- EK3_SRC1_*
local SOURCE_VSLAM = 1  -- EK3_SRC2_*

-- Thresholds from SCR_USER2 / SCR_USER3
local gps_thresh_param = Parameter('SCR_USER2')   -- GPS speed accuracy (m/s)
local extnav_thresh_param = Parameter('SCR_USER3') -- ExternalNav innovation

local vote_counter = 0
local VOTE_THRESHOLD = 20  -- 2 seconds at 10 Hz
local current_source = SOURCE_GPS

function update()
  local gps_thresh = gps_thresh_param:get() or 0.3
  local extnav_thresh = extnav_thresh_param:get() or 0.3

  -- GPS accuracy check
  local gps_spdacc = gps:speed_accuracy(gps:primary_sensor())
  local gps_bad = (gps_spdacc == nil) or (gps_spdacc > gps_thresh)

  -- ExternalNav innovation check
  local extnav_innov = ahrs:get_vel_innovations_and_variances_for_source(6)
  local extnav_bad = (extnav_innov == nil) or
                     (extnav_innov:z() == 0.0) or
                     (math.abs(extnav_innov:z()) > extnav_thresh)

  -- Vote-based switching with stabilization window
  if gps_bad and not extnav_bad then
    vote_counter = math.min(vote_counter + 1, VOTE_THRESHOLD)
  elseif not gps_bad then
    vote_counter = math.max(vote_counter - 1, -VOTE_THRESHOLD)
  end

  local desired = SOURCE_GPS
  if vote_counter >= VOTE_THRESHOLD then
    desired = SOURCE_VSLAM
  elseif vote_counter <= -VOTE_THRESHOLD then
    desired = SOURCE_GPS
  end

  if desired ~= current_source then
    ahrs:set_posvelyaw_source_set(desired)
    current_source = desired
    gcs:send_text(4, string.format(
      "AHRS source: %s", desired == SOURCE_GPS and "GPS" or "VSLAM"))
  end

  return update, math.floor(1000 / FREQ_HZ)
end

return update, math.floor(1000 / FREQ_HZ)
