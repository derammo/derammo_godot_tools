-- Godot RemoteDebugger protocol (size field followed by encoded Variant)

local protocol = Proto("godotdebug", "Godot Debugger Protocol")
protocol.fields.stream = ProtoField.uint8("godotdebug.size", "Stream")
protocol.fields.size = ProtoField.uint32("godotdebug.size", "Size")
protocol.fields.message = ProtoField.string("godotdebug.message", "Message")
protocol.fields.message_command = ProtoField.string("godotdebug.message.command", "Command")
protocol.fields.message_data = ProtoField.string("godotdebug.message.data", "Data")
protocol.fields.unexpected = ProtoField.bytes("godotdebug.unexpected", "UNEXPECTED")
protocol.fields.string = ProtoField.string("godotdebug.string", "STRING")
protocol.fields.int64 = ProtoField.int64("godotdebug.int64", "INT")
protocol.fields.int = ProtoField.int32("godotdebug.int", "INT")
protocol.fields.bool = ProtoField.bool("godotdebug.bool", "BOOL")
protocol.fields.bytes = ProtoField.bytes("godotdebug.bytes", "PACKED_BYTE_ARRAY")
protocol.fields.ubytes = ProtoField.ubytes("godotdebug.ubytes", "PACKED_BYTE_ARRAY")

ENCODED_AS_64BIT = 0x10000

function encode_bool(truth)
    return truth and "true" or "false"
end

function parse_variant(buffer, pinfo, tree, field, child_fields)
    local variant_type = (buffer(0,4):le_uint())
    local consumed = 4
    local is_64_bit = bit.band(variant_type, ENCODED_AS_64BIT) ~= 0
    if is_64_bit then
        variant_type = bit.bxor(variant_type, ENCODED_AS_64BIT)
    end
    if variant_type == 25 then
        local size = buffer(consumed,4):le_uint()
        local item
        if field ~= nil then
            item = tree:add(field, buffer(0, 8), "ARRAY")
        else
            item = tree:add(buffer(0, 8), "ARRAY")
        end
        item:add(buffer(consumed,4), "Size: " .. size)
        consumed = consumed + 4
        for index=1,size do
            local child_field = nil
            if (child_fields ~= nil) and (#child_fields >= index) then
                child_field = child_fields[index]
            end
            local child_consumed = parse_variant(buffer(consumed,-1), pinfo,item, child_field)
            if child_consumed < 0 then
                return child_consumed
            end
            consumed = consumed + child_consumed 
        end
    elseif variant_type == 4 then
        local size = buffer(consumed,4):le_uint()
        consumed = consumed + 4 + size
        while consumed % 4 ~= 0 do
            consumed = consumed + 1
        end
        local text = buffer(8,size):string(ENC_UTF8)
        local item
        if field ~= nil then
            item = tree:add(field, buffer(0, consumed), text)
        else
            item = tree:add(protocol.fields.string, buffer(0, consumed), text)
        end
        item:add(buffer(0, 4), "Type: STRING")
        item:add(buffer(4, 4), "Size: " .. size)
        item:add(buffer(8, size), "Text: " .. text)
    elseif variant_type == 26 then
        local size = buffer(consumed,4):le_uint()
        consumed = consumed + 4 + size
        while consumed % 4 ~= 0 do
            consumed = consumed + 1
        end
        local value = buffer(8, size)
        local item
        if field ~= nil then
            item = tree:add(field, buffer(0, consumed), value:bytes():raw(0, size))
        else
            -- the bytes(...) type does not appear to understand the value having a different size than the range
            -- so we can't set the range to (0, consumed)
            item = tree:add(protocol.fields.bytes, value, value:bytes():raw(0, size))
            -- this is what we would want:
            -- item = tree:add(protocol.fields.bytes, buffer(0, consumed), value:bytes():raw(0, size))
            -- unimplemented in WireShark?
            -- item = tree:add(protocol.fields.ubytes, buffer(0, consumed), value)
        end
        item:add(buffer(0, 4), "Type: PACKED_BYTE_ARRAY")
        item:add(buffer(4, 4), "Size: " .. size)
        item:add(buffer(0, consumed), "Encoded: " .. buffer(0, consumed):bytes():tohex(true))
    elseif variant_type == 2 then
        local value
        local item
        if is_64_bit then
            value = buffer(consumed,8):le_uint64()
            consumed = consumed + 8
        else
            value = buffer(consumed,4):le_uint()
            consumed = consumed + 4
        end
        if is_64_bit then
            if field ~= nil then
                item = tree:add_le(field, buffer(0, consumed), value)
            else
                -- can't override value for some reason
                item = tree:add_le(protocol.fields.int64, buffer(4, 8))
            end
            item:add(buffer(0, 4), "Type: INT")
            item:add(buffer(0, 4), "64 Bit: true")
            item:add(buffer(4, 8), "Value: " .. value)
        else
            if field ~= nil then
                item = tree:add_le(field, buffer(0, consumed), value)
            else
                item = tree:add_le(protocol.fields.int, buffer(4, 4))
            end
            item:add(buffer(0, 4), "Type: INT")
            item:add(buffer(0, 4), "64 Bit: false")
            item:add(buffer(4, 4), "Value: " .. value)
        end
    elseif variant_type == 1 then
        local value
        local item
        if is_64_bit then
            -- doesn't happen, but would be legal
            value = 0 ~= buffer(consumed,8):le_uint64()
            consumed = consumed + 8
        else
            value = 0 ~= buffer(consumed,4):le_uint()
            consumed = consumed + 4
        end
        if field ~= nil then
            item = tree:add_le(field, buffer(0, consumed), value)
        else
            item = tree:add_le(protocol.fields.bool, buffer(0, consumed), value)
        end
        if is_64_bit then
            -- doesn't happen, but would be legal
            item:add(buffer(0, 4), "Type: BOOL")
            item:add(buffer(0, 4), "64 Bit: true")
            item:add(buffer(4, 8), "Value: " .. encode_bool(value))
        else
            item:add(buffer(0, 4), "Type: BOOL")
            item:add(buffer(0, 4), "64 Bit: false")
            item:add(buffer(4, 4), "Value: " .. encode_bool(value))
        end
    else
        local item = tree:add(protocol,buffer(), "UNKNOWN")
        item:add(buffer(0, 4), "Type: " .. variant_type)
        item:add(buffer(0, 4), "64 Bit: " .. encode_bool(is_64_bit))
        consumed = -1
    end
    return consumed
end

function protocol.dissector(buffer,pinfo,tree)
    pinfo.cols.protocol = "godotdebug"

    local subtree = tree:add(protocol, buffer(), "Godot Debugger")
    local size_field = buffer(0, 4):le_uint()
    local size = bit.band(size_field, 0xffffff)
    local stream = bit.band(bit.rshift(size_field, 24), 0xff)
    tree:add_le(protocol.fields.stream, buffer(0, 1), stream)
    tree:add_le(protocol.fields.size, buffer(1, 3), size)
    local consumed = 4
    consumed = consumed + parse_variant(buffer(consumed, -1), pinfo, subtree, protocol.fields.message, { 
        protocol.fields.message_command, 
        protocol.fields.message_data 
    })
    if consumed < buffer:len() then
        tree:add(protocol.fields.unexpected, buffer(consumed, -1))
    end
end

tcp_table = DissectorTable.get("tcp.port")
-- NOTE: collision with X windows
tcp_table:add(6007,protocol)