using System.Formats.Nrbf;

// Parse a BinaryFormatter stream AND fully traverse every record, the way the
// runtime does when it materialises objects. Parsing alone misses errors that
// only surface when members are resolved.
foreach (var path in args)
{
    Console.WriteLine($"=== {Path.GetFileName(path)} ===");
    SerializationRecord root;
    IReadOnlyDictionary<SerializationRecordId, SerializationRecord> map;
    try
    {
        using var fs = File.OpenRead(path);
        root = NrbfDecoder.Decode(fs, out map, leaveOpen: true);
        Console.WriteLine($"  parse OK  records={map.Count}");
    }
    catch (Exception ex)
    {
        Console.WriteLine($"  PARSE FAIL {ex.GetType().Name}: {ex.Message}");
        continue;
    }

    int visited = 0, errors = 0;
    var seen = new HashSet<SerializationRecordId>();

    void Walk(SerializationRecord? r, string where, int depth)
    {
        if (r is null || depth > 40) return;
        if (!seen.Add(r.Id)) return;
        visited++;
        try
        {
            switch (r)
            {
                case ClassRecord cls:
                    foreach (var name in cls.MemberNames)
                    {
                        object? v;
                        try { v = cls.GetRawValue(name); }
                        catch (Exception ex)
                        {
                            errors++;
                            Console.WriteLine($"  MEMBER FAIL {where}/{name} on {cls.TypeName.FullName}: {ex.GetType().Name}: {ex.Message}");
                            continue;
                        }
                        if (v is SerializationRecord sub) Walk(sub, $"{where}/{name}", depth + 1);
                    }
                    break;
                case SZArrayRecord<SerializationRecord?> objArr:
                    foreach (var e in objArr.GetArray()) Walk(e, where + "[]", depth + 1);
                    break;
                case ArrayRecord arr:
                    var flat = arr.GetArray(typeof(object[]));
                    if (flat is Array a)
                        foreach (var e in a) if (e is SerializationRecord s2) Walk(s2, where + "[]", depth + 1);
                    break;
            }
        }
        catch (Exception ex)
        {
            errors++;
            Console.WriteLine($"  WALK FAIL at {where} ({r.GetType().Name}): {ex.GetType().Name}: {ex.Message}");
        }
    }

    // Walk from the root AND every record in the map - BinaryFormatter
    // materialises unreachable records too.
    Walk(root, "root", 0);
    int fromRoot = visited;
    foreach (var kv in map) Walk(kv.Value, $"orphan#{kv.Key}", 0);

    Console.WriteLine($"  walked {visited} records ({fromRoot} from root, {visited - fromRoot} unreferenced)  errors={errors}");
}
